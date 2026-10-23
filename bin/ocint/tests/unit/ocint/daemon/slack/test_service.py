from dataclasses import dataclass, field

import pytest
from ocint.daemon.coordinator import (
    ActorKind,
    ConversationIdentity,
    DeliveryMissing,
    DeliveryReceipt,
    DeliveryRequest,
    MessageKind,
    RetryableCoordinatorError,
)
from ocint.daemon.slack.client import SlackRateLimited
from ocint.daemon.slack.models import SlackEventCallback, SlackEventPayload, SlackMessage, SlackPostedMessage
from ocint.daemon.slack.service import (
    ProductionSlackActorClassifier,
    SlackCoordinatorDelivery,
    translate_slack_event,
)


def test_root_and_reply_translate_to_exact_transport_neutral_identity_and_order() -> None:
    # GIVEN
    classifier = ProductionSlackActorClassifier()
    root = SlackEventCallback(
        team_id="T1",
        event_id="Ev-root",
        event_time=1_754_000_000,
        event=SlackEventPayload(
            type="message",
            channel="C1",
            channel_type="channel",
            user="U1",
            text="root",
            ts="1754000000.123456",
        ),
    )
    reply = SlackEventCallback(
        team_id="T1",
        event_id="Ev-reply",
        event_time=1_754_000_001,
        event=SlackEventPayload(
            type="message",
            channel="C1",
            channel_type="channel",
            user="U1",
            text="reply",
            ts="1754000001.000001",
            thread_ts="1754000000.123456",
        ),
    )

    # WHEN
    translated_root = translate_slack_event(root, classifier)
    translated_reply = translate_slack_event(reply, classifier)

    # THEN
    assert translated_root.kind is MessageKind.ROOT
    assert translated_reply.kind is MessageKind.REPLY
    assert translated_root.actor_kind is ActorKind.HUMAN
    assert translated_reply.message.conversation_identity == translated_root.message.conversation_identity
    assert translated_reply.message.message_id == "1754000001.000001"
    assert translated_reply.message.source_order_at == 1_754_000_001_000_001


@pytest.mark.parametrize(
    ("changes", "expected_kind", "expected_actor"),
    [
        ({"subtype": "message_changed"}, MessageKind.UNSUPPORTED, ActorKind.HUMAN),
        ({"subtype": "message_deleted"}, MessageKind.UNSUPPORTED, ActorKind.HUMAN),
        ({"text": "", "files": ({"id": "F1"},)}, MessageKind.UNSUPPORTED, ActorKind.HUMAN),
        ({"channel_type": "group"}, MessageKind.UNSUPPORTED, ActorKind.HUMAN),
        ({"bot_id": "BBOT", "subtype": "bot_message", "user": "UBOT"}, MessageKind.ROOT, ActorKind.BOT),
        ({"user": ""}, MessageKind.UNSUPPORTED, ActorKind.BOT),
    ],
)
def test_unsupported_message_shapes_are_marked_for_durable_ignore(
    changes: dict[str, str | tuple[dict[str, str], ...]], expected_kind: MessageKind, expected_actor: ActorKind
) -> None:
    # GIVEN
    payload: dict[str, str | tuple[dict[str, str], ...]] = {
        "type": "message",
        "channel": "C1",
        "channel_type": "channel",
        "user": "U1",
        "text": "work",
        "ts": "1754000000.123456",
    }
    payload.update(changes)
    callback = SlackEventCallback.model_validate(
        {"team_id": "T1", "event_id": "Ev1", "event_time": 1_754_000_000, "event": payload}
    )

    # WHEN
    translated = translate_slack_event(callback, ProductionSlackActorClassifier())

    # THEN
    assert translated.kind is expected_kind
    assert translated.actor_kind is expected_actor


@dataclass
class FakeDeliveryTransport:
    found: SlackMessage | None = None
    rate_limited: bool = False
    lookups: list[tuple[str, str, str]] = field(default_factory=list)
    posts: list[tuple[str, str, str, str]] = field(default_factory=list)

    async def find_reply(self, channel: str, root_ts: str, client_msg_id: str) -> SlackMessage | None:
        self.lookups.append((channel, root_ts, client_msg_id))
        return self.found

    async def post_message(self, channel: str, thread_ts: str, text: str, client_msg_id: str) -> SlackPostedMessage:
        self.posts.append((channel, thread_ts, text, client_msg_id))
        if self.rate_limited:
            raise SlackRateLimited(11)
        return SlackPostedMessage(ts="1754000001.000001")


@pytest.mark.asyncio
async def test_coordinator_delivery_uses_identity_thread_for_lookup_and_post() -> None:
    # GIVEN
    transport = FakeDeliveryTransport()
    adapter = SlackCoordinatorDelivery(transport)
    request = DeliveryRequest(
        identity=ConversationIdentity(provider="slack", workspace="T1", channel="C1", thread="1754000000.123456"),
        client_message_id="exact-uuid",
        text="answer",
    )

    # WHEN
    missing = await adapter.find_delivery(request)
    receipt = await adapter.post(request)

    # THEN
    assert isinstance(missing, DeliveryMissing)
    assert receipt == DeliveryReceipt(provider_message_id="1754000001.000001")
    assert transport.lookups == [("C1", "1754000000.123456", "exact-uuid")]
    assert transport.posts == [("C1", "1754000000.123456", "answer", "exact-uuid")]


@pytest.mark.asyncio
async def test_coordinator_delivery_maps_slack_rate_limit_to_retryable_error() -> None:
    # GIVEN
    adapter = SlackCoordinatorDelivery(FakeDeliveryTransport(rate_limited=True))
    request = DeliveryRequest(
        identity=ConversationIdentity(provider="slack", workspace="T1", channel="C1", thread="1754000000.123456"),
        client_message_id="exact-uuid",
        text="answer",
    )

    # WHEN
    with pytest.raises(RetryableCoordinatorError) as raised:
        await adapter.post(request)

    # THEN
    assert raised.value.retry_after_seconds == 11
