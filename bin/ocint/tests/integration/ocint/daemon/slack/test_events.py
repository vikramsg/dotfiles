import asyncio
import hashlib
import hmac
import json
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from ocint.daemon.coordinator import (
    ActorKind,
    ChannelAccess,
    ConfiguredAuthorizationPolicy,
    ConversationMessage,
    CoordinatorRepository,
    CoordinatorService,
    MessageKind,
)
from ocint.daemon.coordinator.models import EventDisposition, IngestResult, PreparedMessage
from ocint.daemon.db import create_daemon_engine
from ocint.daemon.db.schema import coordinator_event, metadata
from ocint.daemon.logging import DaemonLogSettings, close, configure
from ocint.daemon.slack.config import SlackIngressConfig
from ocint.daemon.slack.events import create_slack_events_app
from ocint.daemon.slack.models import SlackEventCallback, SlackPrivateChannelMessage, SlackPublicChannelMessage
from ocint.daemon.slack.service import ProductionSlackActorClassifier, translate_slack_event
from sqlalchemy import func, select


@dataclass(frozen=True)
class PreparedEvent:
    message: ConversationMessage
    kind: MessageKind
    actor_kind: ActorKind


@dataclass
class FakeCoordinator:
    calls: list[str] = field(default_factory=list)
    prepared: list[PreparedEvent] = field(default_factory=list)
    fail_ingest: bool = False

    def prepare(self, message: ConversationMessage, kind: MessageKind, actor_kind: ActorKind) -> PreparedEvent:
        self.calls.append("prepare")
        value = PreparedEvent(message, kind, actor_kind)
        self.prepared.append(value)
        return value

    def ingest(self, prepared: PreparedEvent) -> IngestResult:
        assert prepared in self.prepared
        self.calls.append("ingest")
        if self.fail_ingest:
            raise RuntimeError("database unavailable")
        return IngestResult(disposition=EventDisposition.ACCEPTED)


@pytest.mark.parametrize(
    ("fixture_name", "expected_actor", "expected_bot", "expected_app", "expected_client_message"),
    [
        ("slack-public-human-event.json", ActorKind.HUMAN, "", "", ""),
        (
            "slack-public-xoxp-event.json",
            ActorKind.BOT,
            "B0BNRPSUB8W",
            "A0BNQBTV022",
            "772b8798-747a-44d2-94f8-60350a3cb9e0",
        ),
    ],
)
def test_proven_public_callback_fixtures_parse_and_translate_without_sensitive_material(
    fixture_name: str,
    expected_actor: ActorKind,
    expected_bot: str,
    expected_app: str,
    expected_client_message: str,
) -> None:
    # GIVEN
    fixture = Path(__file__).parents[4] / "fixtures" / "contracts" / fixture_name
    raw = fixture.read_text()

    # WHEN
    callback = SlackEventCallback.model_validate_json(raw)
    translated = translate_slack_event(callback, ProductionSlackActorClassifier())

    # THEN
    assert isinstance(callback.event, SlackPublicChannelMessage)
    assert callback.event.user == "U067EG8278R"
    assert callback.event.bot_id == expected_bot
    assert callback.event.app_id == expected_app
    assert callback.event.client_msg_id == expected_client_message
    assert translated.kind is MessageKind.ROOT
    assert translated.actor_kind is expected_actor
    assert translated.message.conversation_identity.channel == "C0955FD2FK4"
    lowered = raw.lower()
    assert "signature" not in lowered
    assert "token" not in lowered
    assert "xoxp-" not in lowered


@pytest.mark.parametrize(
    ("channel_type", "variant"),
    [("channel", SlackPublicChannelMessage), ("group", SlackPrivateChannelMessage)],
)
def test_public_and_private_channel_messages_use_the_typed_union_and_translate(
    channel_type: str,
    variant: type[SlackPublicChannelMessage] | type[SlackPrivateChannelMessage],
) -> None:
    # GIVEN
    payload = {
        "team_id": "T1",
        "event_id": f"Ev-{channel_type}",
        "event_time": 1_754_000_000,
        "event": {
            "type": "message",
            "channel": "C1",
            "channel_type": channel_type,
            "user": "U1",
            "text": "[typed union fixture]",
            "ts": "1754000000.123456",
        },
    }

    # WHEN
    callback = SlackEventCallback.model_validate(payload)
    translated = translate_slack_event(callback, ProductionSlackActorClassifier())

    # THEN
    assert isinstance(callback.event, variant)
    assert translated.kind is MessageKind.ROOT
    assert translated.actor_kind is ActorKind.HUMAN
    assert "discriminator" not in json.dumps(SlackEventCallback.model_json_schema())


@pytest.mark.asyncio
async def test_ingress_structured_log_contains_only_safe_correlation_fields(tmp_path: Path) -> None:
    # GIVEN
    coordinator = FakeCoordinator()
    body = b'{"type":"event_callback","team_id":"T1","event_id":"Ev-safe","event_time":1754000000,"event":{"type":"message","channel":"C1","channel_type":"channel","user":"U1","text":"PROHIBITED_MARKED_TEXT","ts":"1754000000.123456"}}'
    timestamp = str(int(time.time()))
    signature = "v0=" + hmac.new(b"signing", b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()
    log_path = tmp_path / "daemon.log"
    configure(DaemonLogSettings(path=log_path, max_bytes=1_024, backups=1))
    app = create_slack_events_app(
        SlackIngressConfig(max_request_bytes=1_024, timestamp_tolerance_seconds=300),
        "T1",
        "signing",
        coordinator.prepare,
        coordinator.ingest,
        ProductionSlackActorClassifier(),
        lambda: None,
    )

    # WHEN
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://slack.test") as client:
            response = await client.post(
                "/slack/events",
                content=body,
                headers={"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": signature},
            )
    finally:
        close()
    logged = log_path.read_text()

    # THEN
    assert response.status_code == 200
    assert "workspace=T1" in logged
    assert "channel=C1" in logged
    assert "provider_event=Ev-safe" in logged
    assert "message=1754000000.123456" in logged
    assert "status=200" in logged
    assert "PROHIBITED_MARKED_TEXT" not in logged
    assert "signing" not in logged
    assert signature not in logged


@pytest.mark.asyncio
async def test_signed_event_is_ingested_before_wakeup_with_case_insensitive_headers() -> None:
    # GIVEN
    coordinator = FakeCoordinator()
    body = json.dumps(
        {
            "type": "event_callback",
            "team_id": "T1",
            "event_id": "Ev1",
            "event_time": 1_754_000_000,
            "event": {
                "type": "message",
                "channel": "C1",
                "channel_type": "channel",
                "user": "U1",
                "text": "Root request",
                "ts": "1754000000.123456",
            },
        },
        separators=(",", ":"),
    ).encode()
    timestamp = str(int(time.time()))
    signature = "v0=" + hmac.new(b"signing", b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()

    def wake() -> None:
        coordinator.calls.append("wake")

    app = create_slack_events_app(
        SlackIngressConfig(max_request_bytes=65_536, timestamp_tolerance_seconds=300),
        "T1",
        "signing",
        coordinator.prepare,
        coordinator.ingest,
        ProductionSlackActorClassifier(),
        wake,
    )

    # WHEN
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://slack.test") as client:
        response = await client.post(
            "/slack/events",
            content=body,
            headers={"x-slack-request-timestamp": timestamp, "X-SLACK-SIGNATURE": signature},
        )

    # THEN
    assert response.status_code == 200
    assert coordinator.calls == ["prepare", "ingest", "wake"]
    prepared = coordinator.prepared[0]
    assert prepared.kind is MessageKind.ROOT
    assert prepared.actor_kind is ActorKind.HUMAN
    assert prepared.message.conversation_identity.thread == "1754000000.123456"
    assert prepared.message.source_order_at == 1_754_000_000_123_456


@pytest.mark.asyncio
@pytest.mark.parametrize("authentication", ["missing", "stale", "invalid"])
async def test_missing_stale_or_invalid_authentication_is_rejected_without_ingest(authentication: str) -> None:
    # GIVEN
    coordinator = FakeCoordinator()
    body = b'{"type":"url_verification","team_id":"T1","challenge":"answer"}'
    timestamp = str(int(time.time()) - (301 if authentication == "stale" else 0))
    valid = "v0=" + hmac.new(b"signing", b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()
    headers = {"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": valid}
    if authentication == "missing":
        headers.pop("X-Slack-Signature")
    elif authentication == "invalid":
        headers["X-Slack-Signature"] = "v0=invalid"
    app = create_slack_events_app(
        SlackIngressConfig(max_request_bytes=1_024, timestamp_tolerance_seconds=300),
        "T1",
        "signing",
        coordinator.prepare,
        coordinator.ingest,
        ProductionSlackActorClassifier(),
        lambda: None,
    )

    # WHEN
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://slack.test") as client:
        response = await client.post("/slack/events", content=body, headers=headers)

    # THEN
    assert response.status_code == 401
    assert coordinator.calls == []


@pytest.mark.asyncio
async def test_streamed_body_over_limit_without_content_length_is_rejected() -> None:
    # GIVEN
    coordinator = FakeCoordinator()
    timestamp = str(int(time.time()))
    app = create_slack_events_app(
        SlackIngressConfig(max_request_bytes=8, timestamp_tolerance_seconds=300),
        "T1",
        "signing",
        coordinator.prepare,
        coordinator.ingest,
        ProductionSlackActorClassifier(),
        lambda: None,
    )

    async def content() -> AsyncIterator[bytes]:
        yield b"12345"
        yield b"67890"

    # WHEN
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://slack.test") as client:
        response = await client.post(
            "/slack/events",
            content=content(),
            headers={"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": "v0=unreached"},
        )

    # THEN
    assert response.status_code == 413
    assert coordinator.calls == []


@pytest.mark.asyncio
async def test_signed_url_verification_answers_challenge_and_rejects_other_workspace() -> None:
    # GIVEN
    coordinator = FakeCoordinator()
    timestamp = str(int(time.time()))
    valid_body = b'{"type":"url_verification","team_id":"T1","challenge":"answer"}'
    wrong_body = b'{"type":"url_verification","team_id":"T2","challenge":"answer"}'
    valid_signature = (
        "v0=" + hmac.new(b"signing", b"v0:" + timestamp.encode() + b":" + valid_body, hashlib.sha256).hexdigest()
    )
    wrong_signature = (
        "v0=" + hmac.new(b"signing", b"v0:" + timestamp.encode() + b":" + wrong_body, hashlib.sha256).hexdigest()
    )
    app = create_slack_events_app(
        SlackIngressConfig(max_request_bytes=1_024, timestamp_tolerance_seconds=300),
        "T1",
        "signing",
        coordinator.prepare,
        coordinator.ingest,
        ProductionSlackActorClassifier(),
        lambda: None,
    )

    # WHEN
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://slack.test") as client:
        verified = await client.post(
            "/slack/events",
            content=valid_body,
            headers={"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": valid_signature},
        )
        rejected = await client.post(
            "/slack/events",
            content=wrong_body,
            headers={"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": wrong_signature},
        )

    # THEN
    assert verified.json() == {"challenge": "answer"}
    assert rejected.status_code == 403
    assert coordinator.calls == []


@pytest.mark.asyncio
async def test_database_failure_is_not_acknowledged() -> None:
    # GIVEN
    coordinator = FakeCoordinator(fail_ingest=True)
    body = b'{"type":"event_callback","team_id":"T1","event_id":"Ev1","event_time":1754000000,"event":{"type":"message","channel":"C1","channel_type":"channel","user":"U1","text":"work","ts":"1754000000.123456"}}'
    timestamp = str(int(time.time()))
    signature = "v0=" + hmac.new(b"signing", b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()
    app = create_slack_events_app(
        SlackIngressConfig(max_request_bytes=1_024, timestamp_tolerance_seconds=300),
        "T1",
        "signing",
        coordinator.prepare,
        coordinator.ingest,
        ProductionSlackActorClassifier(),
        lambda: coordinator.calls.append("wake"),
    )

    # WHEN
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://slack.test") as client:
        response = await client.post(
            "/slack/events",
            content=body,
            headers={"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": signature},
        )

    # THEN
    assert response.status_code == 503
    assert coordinator.calls == ["prepare", "ingest"]


@pytest.mark.asyncio
async def test_database_contention_keeps_the_event_loop_responsive_and_returns_503_without_a_late_commit(
    tmp_path: Path,
) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "coordinator.sqlite", busy_timeout_ms=100)
    metadata.create_all(engine)
    repository = CoordinatorRepository(engine)
    service = CoordinatorService(
        ConfiguredAuthorizationPolicy(
            (ChannelAccess(workspace="T1", channel="C1", authorized_actors=frozenset(("U1",))),)
        ),
        3_500,
        "safe failure",
    )
    body = b'{"type":"event_callback","team_id":"T1","event_id":"Ev1","event_time":1754000000,"event":{"type":"message","channel":"C1","channel_type":"channel","user":"U1","text":"work","ts":"1754000000.123456"}}'
    timestamp = str(int(time.time()))
    signature = "v0=" + hmac.new(b"signing", b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()
    app = create_slack_events_app(
        SlackIngressConfig(max_request_bytes=1_024, timestamp_tolerance_seconds=300),
        "T1",
        "signing",
        service.prepare,
        repository.ingest,
        ProductionSlackActorClassifier(),
        lambda: None,
        processing_timeout_seconds=0.5,
    )
    lock = engine.connect()
    lock.exec_driver_sql("BEGIN IMMEDIATE")

    async def event_loop_probe() -> None:
        await asyncio.sleep(0.02)

    # WHEN
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://slack.test") as client:
            probe = asyncio.create_task(event_loop_probe())
            started = time.monotonic()
            response = await client.post(
                "/slack/events",
                content=body,
                headers={"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": signature},
            )
            elapsed = time.monotonic() - started
            responsive = probe.done()
            await probe
    finally:
        lock.rollback()
        lock.close()
    await asyncio.sleep(0.15)
    with engine.connect() as connection:
        event_count = connection.execute(select(func.count()).select_from(coordinator_event)).scalar_one()

    # THEN
    assert response.status_code == 503
    assert responsive
    assert elapsed < 0.5
    assert event_count == 0
    engine.dispose()


@pytest.mark.asyncio
async def test_processing_timeout_returns_promptly_and_observes_late_commit_without_wakeup() -> None:
    # GIVEN
    coordinator = FakeCoordinator()
    commits: list[str] = []
    wakes: list[str] = []
    body = b'{"type":"event_callback","team_id":"T1","event_id":"Ev1","event_time":1754000000,"event":{"type":"message","channel":"C1","channel_type":"channel","user":"U1","text":"work","ts":"1754000000.123456"}}'
    timestamp = str(int(time.time()))
    signature = "v0=" + hmac.new(b"signing", b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()

    def delayed_ingest(prepared: PreparedEvent) -> IngestResult:
        assert prepared in coordinator.prepared
        time.sleep(0.1)
        commits.append("committed")
        return IngestResult(disposition=EventDisposition.ACCEPTED)

    app = create_slack_events_app(
        SlackIngressConfig(max_request_bytes=1_024, timestamp_tolerance_seconds=300),
        "T1",
        "signing",
        coordinator.prepare,
        delayed_ingest,
        ProductionSlackActorClassifier(),
        lambda: wakes.append("wake"),
        processing_timeout_seconds=0.05,
    )

    # WHEN
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://slack.test") as client:
        response = await client.post(
            "/slack/events",
            content=body,
            headers={"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": signature},
        )
    commits_when_returned = tuple(commits)
    await asyncio.sleep(0.1)

    # THEN
    assert response.status_code == 503
    assert commits_when_returned == ()
    assert commits == ["committed"]
    assert wakes == []


@pytest.mark.asyncio
async def test_request_cancellation_returns_immediately_while_late_ingest_finishes_without_wakeup() -> None:
    # GIVEN
    coordinator = FakeCoordinator()
    ingest_started = threading.Event()
    release_ingest = threading.Event()
    ingest_finished = threading.Event()
    wakes: list[str] = []
    body = b'{"type":"event_callback","team_id":"T1","event_id":"Ev-cancel","event_time":1754000000,"event":{"type":"message","channel":"C1","channel_type":"channel","user":"U1","text":"work","ts":"1754000000.123456"}}'
    timestamp = str(int(time.time()))
    signature = "v0=" + hmac.new(b"signing", b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()

    def blocked_ingest(prepared: PreparedEvent) -> IngestResult:
        assert prepared in coordinator.prepared
        ingest_started.set()
        release_ingest.wait()
        ingest_finished.set()
        return IngestResult(disposition=EventDisposition.ACCEPTED)

    app = create_slack_events_app(
        SlackIngressConfig(max_request_bytes=1_024, timestamp_tolerance_seconds=300),
        "T1",
        "signing",
        coordinator.prepare,
        blocked_ingest,
        ProductionSlackActorClassifier(),
        lambda: wakes.append("wake"),
        processing_timeout_seconds=2,
    )

    # WHEN
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://slack.test") as client:
            request = asyncio.create_task(
                client.post(
                    "/slack/events",
                    content=body,
                    headers={"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": signature},
                )
            )
            async with asyncio.timeout(1):
                while not ingest_started.is_set():
                    await asyncio.sleep(0.001)
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(request, 0.1)
    finally:
        release_ingest.set()
        assert await asyncio.to_thread(ingest_finished.wait, 1)
        await asyncio.sleep(0)

    # THEN
    assert wakes == []


@pytest.mark.asyncio
async def test_duplicate_signed_delivery_returns_success_with_one_durable_turn(tmp_path: Path) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "coordinator.sqlite")
    metadata.create_all(engine)
    repository = CoordinatorRepository(engine)
    service = CoordinatorService(
        ConfiguredAuthorizationPolicy(
            (ChannelAccess(workspace="T1", channel="C1", authorized_actors=frozenset(("U1",))),)
        ),
        3_500,
        "safe failure",
    )
    results: list[IngestResult] = []
    durable_counts_at_wake: list[int] = []

    def ingest(prepared: PreparedMessage) -> IngestResult:
        result = repository.ingest(prepared)
        results.append(result)
        return result

    def wake() -> None:
        with engine.connect() as connection:
            durable_counts_at_wake.append(
                connection.execute(select(func.count()).select_from(coordinator_event)).scalar_one()
            )

    body = b'{"type":"event_callback","team_id":"T1","event_id":"Ev1","event_time":1754000000,"event":{"type":"message","channel":"C1","channel_type":"channel","user":"U1","text":"work","ts":"1754000000.123456"}}'
    timestamp = str(int(time.time()))
    signature = "v0=" + hmac.new(b"signing", b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()
    app = create_slack_events_app(
        SlackIngressConfig(max_request_bytes=1_024, timestamp_tolerance_seconds=300),
        "T1",
        "signing",
        service.prepare,
        ingest,
        ProductionSlackActorClassifier(),
        wake,
    )

    # WHEN
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://slack.test") as client:
        first = await client.post(
            "/slack/events",
            content=body,
            headers={"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": signature},
        )
        duplicate = await client.post(
            "/slack/events",
            content=body,
            headers={"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": signature},
        )

    # THEN
    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert [result.disposition for result in results] == [EventDisposition.ACCEPTED, EventDisposition.DUPLICATE]
    assert durable_counts_at_wake == [1, 1]
    assert len(repository.turns(results[0].conversation_id)) == 1
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_fields", "authorized_actor"),
    [
        ({"bot_id": "BBOT", "subtype": "bot_message", "user": "UBOT"}, "UBOT"),
        ({"subtype": "message_changed"}, "U1"),
        ({"channel": "C2"}, "U1"),
    ],
)
async def test_bot_subtype_and_unconfigured_channel_events_are_durably_ignored(
    tmp_path: Path, event_fields: dict[str, str], authorized_actor: str
) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "coordinator.sqlite")
    metadata.create_all(engine)
    repository = CoordinatorRepository(engine)
    service = CoordinatorService(
        ConfiguredAuthorizationPolicy(
            (ChannelAccess(workspace="T1", channel="C1", authorized_actors=frozenset((authorized_actor,))),)
        ),
        3_500,
        "safe failure",
    )
    results: list[IngestResult] = []

    def ingest(prepared: PreparedMessage) -> IngestResult:
        result = repository.ingest(prepared)
        results.append(result)
        return result

    event = {
        "type": "message",
        "channel": "C1",
        "channel_type": "channel",
        "user": "U1",
        "text": "work",
        "ts": "1754000000.123456",
    }
    event.update(event_fields)
    body = json.dumps(
        {
            "type": "event_callback",
            "team_id": "T1",
            "event_id": "Ev1",
            "event_time": 1_754_000_000,
            "event": event,
        },
        separators=(",", ":"),
    ).encode()
    timestamp = str(int(time.time()))
    signature = "v0=" + hmac.new(b"signing", b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()
    app = create_slack_events_app(
        SlackIngressConfig(max_request_bytes=1_024, timestamp_tolerance_seconds=300),
        "T1",
        "signing",
        service.prepare,
        ingest,
        ProductionSlackActorClassifier(),
        lambda: None,
    )

    # WHEN
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://slack.test") as client:
        response = await client.post(
            "/slack/events",
            content=body,
            headers={"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": signature},
        )

    # THEN
    assert response.status_code == 200
    assert results[0].disposition is EventDisposition.IGNORED
    assert results[0].turn_ids == ()
    engine.dispose()
