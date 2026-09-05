from ocint.daemon.coordinator import (
    ActorKind,
    ChannelAccess,
    ConversationIdentity,
    ConversationMessage,
    MessageKind,
)
from ocint.daemon.coordinator.models import AuthorizationDecision
from ocint.daemon.coordinator.service import ConfiguredAuthorizationPolicy, CoordinatorService


def test_authorization_rejects_bots_and_accepts_only_configured_humans() -> None:
    # GIVEN
    message = ConversationMessage(
        provider_event_id="event",
        conversation_identity=ConversationIdentity(provider="chat", workspace="w", channel="c", thread="root"),
        message_id="root",
        actor_id="alice",
        text="question",
        source_created_at="1.000001",
        source_order_at=1_000_001,
    )
    policy = ConfiguredAuthorizationPolicy(
        (ChannelAccess(provider="chat", workspace="w", channel="c", authorized_actors=frozenset(("alice",))),)
    )
    service = CoordinatorService(policy, 100, "Please try again later.")

    # WHEN
    human = service.prepare(message, MessageKind.ROOT, ActorKind.HUMAN)
    bot = service.prepare(message, MessageKind.REPLY, ActorKind.BOT)

    # THEN
    assert human.decision is AuthorizationDecision.AUTHORIZED
    assert bot.decision is AuthorizationDecision.UNAUTHORIZED
    assert human.managed_prompt.endswith("\n\nquestion")


def test_authorization_denies_an_identical_channel_from_another_provider() -> None:
    # GIVEN
    policy = ConfiguredAuthorizationPolicy(
        (ChannelAccess(provider="chat", workspace="w", channel="c", authorized_actors=frozenset(("alice",))),)
    )
    service = CoordinatorService(policy, 100, "Please try again later.")
    message = ConversationMessage(
        provider_event_id="event",
        conversation_identity=ConversationIdentity(provider="other-chat", workspace="w", channel="c", thread="root"),
        message_id="root",
        actor_id="alice",
        text="question",
        source_created_at="1.000001",
        source_order_at=1_000_001,
    )

    # WHEN
    prepared = service.prepare(message, MessageKind.ROOT, ActorKind.HUMAN)

    # THEN
    assert prepared.decision is AuthorizationDecision.UNAUTHORIZED


def test_chunking_counts_unicode_code_points_and_reconstructs_the_full_response() -> None:
    # GIVEN
    policy = ConfiguredAuthorizationPolicy(
        (ChannelAccess(provider="chat", workspace="w", channel="c", authorized_actors=frozenset(("alice",))),)
    )
    service = CoordinatorService(policy, 40, "safe")
    response = "🙂" * 73 + "\n\n" + "words " * 20

    # WHEN
    chunks = service.chunks(response)

    # THEN
    assert all(len(chunk.text) <= 40 for chunk in chunks)
    assert all(chunk.text.startswith(f"[{chunk.index}/{len(chunks)}] ") for chunk in chunks)
    assert service.reconstruct(chunks) == response
