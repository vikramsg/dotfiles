import uuid
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse

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
    parse_slack_timestamp,
)
from ocint.daemon.logging import get_logger
from ocint.daemon.models import (
    ActorIdentity,
    MessageClassification,
    ObservedMessage,
    ObservedMessages,
    ReplyOutcome,
    ReplyRequest,
    ThreadObservation,
    ThreadObservations,
)
from ocint.daemon.slack.client import SlackApiError, SlackRateLimited, SlackRetryableError
from ocint.daemon.slack.config import SlackChannelConfig, SlackConfig
from ocint.daemon.slack.models import (
    SlackAuth,
    SlackEventCallback,
    SlackHistory,
    SlackMessage,
    SlackPostedMessage,
    SlackRootReference,
    StoredSlackThread,
)
from ocint.daemon.slack.repository import SlackRepository


@runtime_checkable
class SlackTransport(Protocol):
    async def auth_test(self) -> SlackAuth: ...
    async def history(self, channel: str, oldest: str = "", cursor: str = "") -> SlackHistory: ...
    async def replies(self, channel: str, root_ts: str, cursor: str = "") -> SlackHistory: ...
    async def post_message(self, channel: str, thread_ts: str, text: str, client_msg_id: str) -> SlackPostedMessage: ...
    async def add_reaction(self, channel: str, timestamp: str, name: str) -> None: ...


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
        and event.channel_type in ("channel", "group")
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


class SlackContext(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    config: SlackConfig
    auth: SlackAuth
    client: SlackTransport
    repository: SlackRepository


class SlackService(BaseModel):
    model_config = ConfigDict(frozen=True)
    context: SlackContext

    @property
    def source_prefix(self) -> str:
        return "slack:"

    async def observe(self) -> ThreadObservations:
        observations: list[ThreadObservation] = []
        for channel in self.context.config.channels:
            if self.context.repository.deferred(channel.channel_id):
                observations.extend(self._stored_observations(channel.channel_id))
                continue
            try:
                observations.extend(await self._observe_channel(channel))
            except SlackRateLimited as error:
                self.context.repository.defer(channel.channel_id, error.retry_after_seconds)
                observations.extend(self._stored_observations(channel.channel_id))
        return ThreadObservations(root=observations)

    async def _observe_channel(self, channel: SlackChannelConfig) -> list[ThreadObservation]:
        observations: list[ThreadObservation] = []
        watermark = self.context.repository.watermark(channel.channel_id)
        oldest = watermark or channel.initial_oldest
        roots = [
            item
            for item in await self._history(channel.channel_id, oldest)
            if (item.ts > watermark if watermark else item.ts >= channel.initial_oldest)
        ]
        for root in sorted(roots, key=lambda item: item.ts):
            if root.thread_ts and root.thread_ts != root.ts:
                continue
            reopen_command = root.text.startswith("reopen ") and "\n" not in root.text
            reopen = self._reopen_target(root.text)
            previous = (
                self.context.repository.by_root(self.context.config.workspace_id, reopen.channel_id, reopen.root_ts)
                if reopen is not None
                else None
            )
            authorized = root.user in channel.authorized_users
            reopened = False
            if previous is not None and authorized:
                try:
                    stored = self.context.repository.reopen(
                        previous,
                        self.context.config.workspace_id,
                        channel.channel_id,
                        root.ts,
                        channel.repository,
                    )
                    reopened = True
                except ValueError:
                    stored = self._new_thread(channel.channel_id, channel.repository, root, False)
                self.context.repository.upsert_message(
                    channel.channel_id, root.ts, root.ts, root.user, root.text, MessageClassification.AGENT_RESPONSE
                )
            else:
                stored = self._new_thread(
                    channel.channel_id,
                    channel.repository,
                    root,
                    authorized and not reopen_command,
                )
            observations.append(
                await self._observe_thread(
                    stored,
                    channel.authorized_users,
                    reopened or (reopen_command and authorized),
                )
            )
        if roots:
            self.context.repository.set_watermark(channel.channel_id, max(item.ts for item in roots))
        observed = {
            (item.source_id, item.messages.root[0].source_id if item.messages.root else "") for item in observations
        }
        for stored in self.context.repository.open_threads(channel.channel_id):
            identity = (stored.logical_source_id, self._message_id(stored.channel_id, stored.root_ts))
            if identity not in observed:
                observations.append(await self._observe_thread(stored, channel.authorized_users))
        return observations

    def _stored_observations(self, channel_id: str) -> list[ThreadObservation]:
        return [
            ThreadObservation(
                source_id=stored.logical_source_id,
                configured_repository=stored.configured_repository,
                title=stored.title,
                eligible=stored.authorized,
                messages=ObservedMessages(root=[]),
            )
            for stored in self.context.repository.open_threads(channel_id)
        ]

    async def reply(self, request: ReplyRequest) -> ObservedMessage:
        thread = self.context.repository.thread(request.source_thread_id)
        if thread is None:
            raise RuntimeError(f"Slack mapping missing for source {request.source_thread_id}")
        key = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"ocint:{request.source_thread_id}:{request.source_anchor_id}:{request.outcome.value}",
            )
        )
        timestamp = self.context.repository.begin_reply(key, thread.channel_id)
        if not timestamp:
            remote = next(
                (
                    message
                    for message in await self._replies(thread.channel_id, thread.root_ts)
                    if message.client_msg_id == key
                ),
                None,
            )
            if remote is None:
                posted = await self.context.client.post_message(thread.channel_id, thread.root_ts, request.text, key)
                timestamp = posted.ts
            else:
                timestamp = remote.ts
            self.context.repository.save_reply(key, thread.channel_id, timestamp)
        if request.outcome in {ReplyOutcome.ADDRESSED, ReplyOutcome.CLOSED_PULL_REQUEST}:
            await self.context.client.add_reaction(
                thread.channel_id, thread.root_ts, self.context.config.completion_reaction
            )
            self.context.repository.close(thread.channel_id, thread.root_ts)
        message = ObservedMessage(
            source_id=self._message_id(thread.channel_id, timestamp),
            actor=ActorIdentity(f"slack:{self.context.auth.user_id}"),
            classification=MessageClassification.AGENT_RESPONSE,
            body=request.text,
            source_created_at=timestamp,
        )
        self.context.repository.upsert_message(
            thread.channel_id,
            thread.root_ts,
            timestamp,
            self.context.auth.user_id,
            request.text,
            message.classification,
        )
        return message

    async def _observe_thread(
        self, thread: StoredSlackThread, authorized_users: frozenset[str], suppress_root: bool = False
    ) -> ThreadObservation:
        messages = await self._replies(thread.channel_id, thread.root_ts)
        observed: list[ObservedMessage] = []
        for message in messages:
            classification = (
                MessageClassification.AGENT_RESPONSE
                if (suppress_root or thread.reopen_root) and message.ts == thread.root_ts
                else self._classification(message, authorized_users)
            )
            self.context.repository.upsert_message(
                thread.channel_id, thread.root_ts, message.ts, message.user, message.text, classification
            )
            observed.append(
                ObservedMessage(
                    source_id=self._message_id(thread.channel_id, message.ts),
                    actor=ActorIdentity(f"slack:{message.user or self.context.auth.user_id}"),
                    classification=classification,
                    body=message.text,
                    source_created_at=message.ts,
                )
            )
        return ThreadObservation(
            source_id=thread.logical_source_id,
            configured_repository=thread.configured_repository,
            title=thread.title,
            eligible=thread.authorized,
            messages=ObservedMessages(root=observed),
        )

    def _classification(self, message: SlackMessage, authorized_users: frozenset[str]) -> MessageClassification:
        if message.user == self.context.auth.user_id or (message.bot_id and message.bot_id == self.context.auth.bot_id):
            return MessageClassification.AGENT_RESPONSE
        return (
            MessageClassification.ACTIONABLE if message.user in authorized_users else MessageClassification.UNAUTHORIZED
        )

    async def _history(self, channel: str, oldest: str) -> list[SlackMessage]:
        values: list[SlackMessage] = []
        cursor = ""
        while True:
            page = await self.context.client.history(channel, oldest, cursor)
            values.extend(page.messages.root)
            cursor = page.response_metadata.next_cursor
            if not cursor:
                return values

    async def _replies(self, channel: str, root_ts: str) -> list[SlackMessage]:
        values: list[SlackMessage] = []
        cursor = ""
        while True:
            page = await self.context.client.replies(channel, root_ts, cursor)
            values.extend(page.messages.root)
            cursor = page.response_metadata.next_cursor
            if not cursor:
                return values

    def _new_thread(
        self, channel_id: str, configured_repository: str, root: SlackMessage, authorized: bool
    ) -> StoredSlackThread:
        source_id = SlackRepository.root_identity(self.context.config.workspace_id, channel_id, root.ts)
        return self.context.repository.upsert_thread(
            StoredSlackThread(
                channel_id=channel_id,
                root_ts=root.ts,
                workspace_id=self.context.config.workspace_id,
                logical_source_id=source_id,
                root_identity=source_id,
                configured_repository=configured_repository,
                title=self._title(root.text),
                authorized=authorized,
                closed=False,
                reopen_root=False,
            )
        )

    @staticmethod
    def _reopen_target(body: str) -> SlackRootReference | None:
        prefix = "reopen "
        if not body.startswith(prefix) or "\n" in body:
            return None
        target = body[len(prefix) :]
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1].split("|", maxsplit=1)[0]
        parsed = urlparse(target)
        parts = parsed.path.strip("/").split("/")
        if parsed.scheme != "https" or len(parts) != 3 or parts[0] != "archives" or not parts[2].startswith("p"):
            return None
        packed = parts[2][1:]
        if not packed.isdigit() or len(packed) <= 6:
            return None
        return SlackRootReference(channel_id=parts[1], root_ts=f"{packed[:-6]}.{packed[-6:]}")

    @staticmethod
    def _title(body: str) -> str:
        return next((line.strip() for line in body.splitlines() if line.strip()), "Slack request")

    @staticmethod
    def _message_id(channel_id: str, timestamp: str) -> str:
        return f"slack:{channel_id}:message:{timestamp}"
