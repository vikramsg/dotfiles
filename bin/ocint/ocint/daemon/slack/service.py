from typing import Protocol

from pydantic import BaseModel, ConfigDict

from ocint.daemon.coordinator import (
    ActorKind,
    ConversationIdentity,
    ConversationMessage,
    DeliveryLookup,
    DeliveryMissing,
    DeliveryReceipt,
    DeliveryRequest,
    MessageKind,
    RetryableCoordinatorError,
    TerminalCoordinatorError,
)
from ocint.daemon.logging import get_logger
from ocint.daemon.slack.client import SlackApiError, SlackRetryableError
from ocint.daemon.slack.models import (
    SlackEventCallback,
    SlackMessage,
    SlackPostedMessage,
    parse_slack_timestamp,
)


class SlackActorClassifier(Protocol):
    def classify(self, callback: SlackEventCallback) -> ActorKind: ...


class ProductionSlackActorClassifier:
    def classify(self, callback: SlackEventCallback) -> ActorKind:
        event = callback.event
        if (
            event.bot_id
            or event.bot_profile is not None
            or event.app_id
            or event.subtype == "bot_message"
            or not event.user
        ):
            return ActorKind.BOT
        return ActorKind.HUMAN


class TranslatedSlackEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    message: ConversationMessage
    kind: MessageKind
    actor_kind: ActorKind


def translate_slack_event(callback: SlackEventCallback, actor_classifier: SlackActorClassifier) -> TranslatedSlackEvent:
    event = callback.event
    actor_kind = actor_classifier.classify(callback)
    timestamp_valid = True
    try:
        source_order_at = parse_slack_timestamp(event.ts)
        message_id = event.ts
    except ValueError:
        timestamp_valid = False
        source_order_at = callback.event_time * 1_000_000
        message_id = f"{callback.event_time}.000000"

    thread_valid = True
    thread_id = event.thread_ts or message_id
    if event.thread_ts:
        try:
            parse_slack_timestamp(event.thread_ts)
        except ValueError:
            thread_valid = False
            thread_id = message_id

    supported = (
        event.type == "message"
        and event.channel_type == "channel"
        and event.subtype in ("", "bot_message")
        and bool(event.text.strip())
        and bool(event.channel)
        and bool(event.user or event.bot_id)
        and timestamp_valid
        and thread_valid
    )
    if not supported:
        kind = MessageKind.UNSUPPORTED
    elif event.thread_ts and event.thread_ts != event.ts:
        kind = MessageKind.REPLY
    else:
        kind = MessageKind.ROOT

    return TranslatedSlackEvent(
        message=ConversationMessage(
            provider_event_id=callback.event_id,
            conversation_identity=ConversationIdentity(
                provider="slack",
                workspace=callback.team_id,
                channel=event.channel or "unsupported",
                thread=thread_id,
            ),
            message_id=message_id,
            actor_id=event.user or event.bot_id or "unsupported",
            text=event.text,
            source_created_at=message_id,
            source_order_at=source_order_at,
        ),
        kind=kind,
        actor_kind=actor_kind,
    )


class SlackDeliveryTransport(Protocol):
    async def find_reply(self, channel: str, root_ts: str, client_msg_id: str) -> SlackMessage | None: ...
    async def post_message(self, channel: str, thread_ts: str, text: str, client_msg_id: str) -> SlackPostedMessage: ...


class SlackCoordinatorDelivery:
    def __init__(self, client: SlackDeliveryTransport) -> None:
        self.client = client
        self.logger = get_logger("slack.delivery")

    async def find_delivery(self, request: DeliveryRequest) -> DeliveryLookup:
        self.logger.info(
            "Slack delivery lookup started",
            workspace=request.identity.workspace,
            channel=request.identity.channel,
            thread=request.identity.thread,
            client_message=request.client_message_id,
        )
        try:
            message = await self.client.find_reply(
                request.identity.channel,
                request.identity.thread,
                request.client_message_id,
            )
        except SlackRetryableError as error:
            self.logger.warning(
                "Slack delivery lookup retry required",
                channel=request.identity.channel,
                thread=request.identity.thread,
                client_message=request.client_message_id,
                error_type=type(error).__name__,
                retry_after=error.retry_after_seconds,
            )
            raise RetryableCoordinatorError(
                "Slack delivery lookup failed temporarily", error.retry_after_seconds
            ) from error
        except SlackApiError as error:
            raise TerminalCoordinatorError("Slack delivery lookup was rejected") from error
        if message is None:
            self.logger.info(
                "Slack delivery lookup missing",
                channel=request.identity.channel,
                thread=request.identity.thread,
                client_message=request.client_message_id,
            )
            return DeliveryMissing()
        self.logger.info(
            "Slack delivery lookup recovered",
            channel=request.identity.channel,
            thread=request.identity.thread,
            client_message=request.client_message_id,
            provider_message=message.ts,
        )
        return DeliveryReceipt(provider_message_id=message.ts)

    async def post(self, request: DeliveryRequest) -> DeliveryReceipt:
        self.logger.info(
            "Slack delivery post started",
            workspace=request.identity.workspace,
            channel=request.identity.channel,
            thread=request.identity.thread,
            client_message=request.client_message_id,
        )
        try:
            posted = await self.client.post_message(
                request.identity.channel,
                request.identity.thread,
                request.text,
                request.client_message_id,
            )
        except SlackRetryableError as error:
            self.logger.warning(
                "Slack delivery post retry required",
                channel=request.identity.channel,
                thread=request.identity.thread,
                client_message=request.client_message_id,
                error_type=type(error).__name__,
                retry_after=error.retry_after_seconds,
            )
            raise RetryableCoordinatorError("Slack delivery failed temporarily", error.retry_after_seconds) from error
        except SlackApiError as error:
            raise TerminalCoordinatorError("Slack delivery was rejected") from error
        self.logger.info(
            "Slack delivery post completed",
            channel=request.identity.channel,
            thread=request.identity.thread,
            client_message=request.client_message_id,
            provider_message=posted.ts,
        )
        return DeliveryReceipt(provider_message_id=posted.ts)
