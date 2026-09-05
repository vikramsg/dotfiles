import pytest
from ocint.daemon.coordinator import ConversationIdentity
from pydantic import ValidationError


def test_conversation_models_are_frozen() -> None:
    # GIVEN
    identity = ConversationIdentity(provider="chat", workspace="w", channel="c", thread="t")

    # WHEN / THEN
    with pytest.raises(ValidationError, match="Instance is frozen"):
        identity.thread = "other"
