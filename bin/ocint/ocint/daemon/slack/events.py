import asyncio
import hashlib
import hmac
import time
from collections.abc import Callable
from typing import Never, Protocol

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError
from starlette.responses import JSONResponse, Response

from ocint.daemon.coordinator import ActorKind, ConversationMessage, IngestResult, MessageKind
from ocint.daemon.logging import get_logger
from ocint.daemon.slack.config import SlackIngressConfig
from ocint.daemon.slack.models import SlackEventCallback, SlackEventsEnvelope, SlackUrlVerification
from ocint.daemon.slack.service import SlackActorClassifier, translate_slack_event


class CoordinatorPrepare[Prepared](Protocol):
    def __call__(self, message: ConversationMessage, kind: MessageKind, actor_kind: ActorKind, /) -> Prepared: ...


class CoordinatorIngest[Prepared](Protocol):
    def __call__(self, prepared: Prepared, /) -> IngestResult: ...


class IngressCorrelation(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace: str
    channel: str
    thread: str
    provider_event: str
    message: str


class SlackEventsIngress[Prepared]:
    def __init__(
        self,
        config: SlackIngressConfig,
        workspace_id: str,
        signing_secret: str,
        prepare: CoordinatorPrepare[Prepared],
        ingest: CoordinatorIngest[Prepared],
        actor_classifier: SlackActorClassifier,
        wake: Callable[[], None],
        processing_timeout_seconds: float,
    ) -> None:
        if not workspace_id:
            raise ValueError("Slack workspace ID must not be empty")
        if not signing_secret:
            raise ValueError("Slack signing secret must not be empty")
        if processing_timeout_seconds <= 0 or processing_timeout_seconds >= 3:
            raise ValueError("Slack ingress processing timeout must be positive and less than 3 seconds")
        self.config = config
        self.workspace_id = workspace_id
        self.signing_secret = signing_secret
        self.prepare = prepare
        self.ingest = ingest
        self.actor_classifier = actor_classifier
        self.wake = wake
        self.processing_timeout_seconds = processing_timeout_seconds
        self.envelopes = TypeAdapter(SlackEventsEnvelope)
        self.logger = get_logger("slack.ingress")

    async def handle(self, request: Request) -> Response:
        raw_body = await self._read_body(request)
        timestamp, signature = self._authenticate(request, raw_body)
        del timestamp, signature
        envelope = self._parse(raw_body)
        if envelope.team_id != self.workspace_id:
            self._reject(403, "workspace", len(raw_body))
        self.logger.info(
            "Slack ingress authenticated",
            workspace=envelope.team_id,
            request_bytes=len(raw_body),
            envelope_type=envelope.type,
        )
        if isinstance(envelope, SlackUrlVerification):
            return JSONResponse({"challenge": envelope.challenge})
        if not isinstance(envelope, SlackEventCallback):
            self._reject(400, "envelope", len(raw_body))

        translated = translate_slack_event(envelope, self.actor_classifier)
        message = translated.message
        identity = message.conversation_identity
        correlation = IngressCorrelation(
            workspace=identity.workspace,
            channel=identity.channel,
            thread=identity.thread,
            provider_event=message.provider_event_id,
            message=message.message_id,
        )
        self.logger.info("Slack event dispatch started", **correlation.model_dump())
        prepared = self.prepare(message, translated.kind, translated.actor_kind)
        ingest_task = asyncio.create_task(asyncio.to_thread(self.ingest, prepared))
        try:
            result = await asyncio.wait_for(asyncio.shield(ingest_task), self.processing_timeout_seconds)
        except TimeoutError:
            ingest_task.add_done_callback(lambda task: self._observe_late_ingest(task, correlation))
            self.logger.warning("Slack event dispatch timed out", status=503, **correlation.model_dump())
            raise HTTPException(status_code=503, detail="Slack event could not be committed") from None
        except asyncio.CancelledError:
            ingest_task.add_done_callback(lambda task: self._observe_late_ingest(task, correlation))
            raise
        except Exception as error:
            self.logger.warning(
                "Slack event dispatch failed",
                status=503,
                error_type=type(error).__name__,
                **correlation.model_dump(),
            )
            raise HTTPException(status_code=503, detail="Slack event could not be committed") from None
        self.logger.info(
            "Slack event dispatch completed",
            state=result.disposition.value,
            status=200,
            **correlation.model_dump(),
        )
        self.wake()
        return Response(status_code=200)

    async def _read_body(self, request: Request) -> bytes:
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > self.config.max_request_bytes:
                self._reject(413, "request_size", len(body) + len(chunk))
            body.extend(chunk)
        return bytes(body)

    def _authenticate(self, request: Request, raw_body: bytes) -> tuple[str, str]:
        timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
        signature = request.headers.get("X-Slack-Signature", "")
        if not timestamp or not signature:
            self._reject(401, "authentication_missing", len(raw_body))
        if not timestamp.isdigit():
            self._reject(401, "timestamp_invalid", len(raw_body))
        signed_at = int(timestamp)
        if abs(int(time.time()) - signed_at) > self.config.timestamp_tolerance_seconds:
            self._reject(401, "timestamp_stale", len(raw_body))
        expected = (
            "v0="
            + hmac.new(
                self.signing_secret.encode(),
                b"v0:" + timestamp.encode() + b":" + raw_body,
                hashlib.sha256,
            ).hexdigest()
        )
        if not hmac.compare_digest(expected, signature):
            self._reject(401, "signature_invalid", len(raw_body))
        return timestamp, signature

    def _parse(self, raw_body: bytes) -> SlackEventsEnvelope:
        try:
            return self.envelopes.validate_json(raw_body)
        except ValidationError:
            self._reject(400, "payload_invalid", len(raw_body))

    def _reject(self, status: int, reason: str, request_bytes: int) -> Never:
        self.logger.warning("Slack ingress rejected", status=status, reason=reason, request_bytes=request_bytes)
        raise HTTPException(status_code=status, detail="Slack request was rejected")

    def _observe_late_ingest(self, task: asyncio.Task[IngestResult], correlation: IngressCorrelation) -> None:
        try:
            result = task.result()
        except asyncio.CancelledError:
            self.logger.warning("Slack timed-out dispatch cancelled", **correlation.model_dump())
        except Exception as error:
            self.logger.warning(
                "Slack timed-out dispatch failed",
                error_type=type(error).__name__,
                **correlation.model_dump(),
            )
        else:
            self.logger.info(
                "Slack timed-out dispatch completed",
                state=result.disposition.value,
                **correlation.model_dump(),
            )


def create_slack_events_app[Prepared](
    config: SlackIngressConfig,
    workspace_id: str,
    signing_secret: str,
    prepare: CoordinatorPrepare[Prepared],
    ingest: CoordinatorIngest[Prepared],
    actor_classifier: SlackActorClassifier,
    wake: Callable[[], None],
    processing_timeout_seconds: float = 2.5,
) -> FastAPI:
    ingress = SlackEventsIngress(
        config,
        workspace_id,
        signing_secret,
        prepare,
        ingest,
        actor_classifier,
        wake,
        processing_timeout_seconds,
    )
    app = FastAPI(title="ocint Slack events", docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/slack/events")
    async def slack_events(request: Request) -> Response:
        return await ingress.handle(request)

    return app
