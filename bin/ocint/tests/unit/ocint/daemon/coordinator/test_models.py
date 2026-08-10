import pytest
from ocint.daemon.coordinator import ConversationIdentity, ConversationMessage, parse_slack_timestamp
from pydantic import ValidationError


def test_slack_timestamp_uses_exact_integer_ordering_without_float_rounding() -> None:
    # GIVEN
    timestamp = "9999999999.999999"

    # WHEN
    order = parse_slack_timestamp(timestamp)
    message = ConversationMessage(
        provider_event_id="event-1",
        conversation_identity=ConversationIdentity(
            provider="slack", workspace="workspace", channel="channel", thread="9999999999.999999"
        ),
        message_id=timestamp,
        actor_id="actor",
        text="hello",
        source_created_at=timestamp,
        source_order_at=order,
    )

    # THEN
    assert order == 9_999_999_999_999_999
    assert message.source_order_at == order
    with pytest.raises(ValueError, match="invalid Slack timestamp"):
        parse_slack_timestamp("9999999999.1")


def test_conversation_models_are_frozen() -> None:
    # GIVEN
    identity = ConversationIdentity(provider="slack", workspace="w", channel="c", thread="t")

    # WHEN / THEN
    with pytest.raises(ValidationError, match="Instance is frozen"):
        identity.thread = "other"
