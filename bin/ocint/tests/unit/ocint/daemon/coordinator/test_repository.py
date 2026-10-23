from pathlib import Path

import pytest
from ocint.daemon.coordinator import (
    ActorKind,
    ChannelAccess,
    ConversationIdentity,
    ConversationMessage,
    MessageKind,
)
from ocint.daemon.coordinator.models import ConversationState, EventDisposition, ResponseChunk, TurnState
from ocint.daemon.coordinator.repository import CoordinatorRepository
from ocint.daemon.coordinator.service import ConfiguredAuthorizationPolicy, CoordinatorService
from ocint.daemon.db import create_daemon_engine
from ocint.daemon.db.schema import metadata


@pytest.fixture
def repository(tmp_path: Path) -> CoordinatorRepository:
    engine = create_daemon_engine(tmp_path / "coordinator.sqlite")
    metadata.create_all(engine)
    return CoordinatorRepository(engine)


@pytest.fixture
def service() -> CoordinatorService:
    policy = ConfiguredAuthorizationPolicy(
        (ChannelAccess(provider="chat", workspace="w", channel="c", authorized_actors=frozenset(("alice",))),)
    )
    return CoordinatorService(policy, 100, "safe")


def test_reply_waits_for_root_then_all_turns_are_created_in_exact_source_order(
    repository: CoordinatorRepository, service: CoordinatorService
) -> None:
    # GIVEN
    identity = ConversationIdentity(provider="chat", workspace="w", channel="c", thread="1.000001")
    reply = ConversationMessage(
        provider_event_id="reply-event",
        conversation_identity=identity,
        message_id="1.000003",
        actor_id="alice",
        text="reply",
        source_created_at="1.000003",
        source_order_at=1_000_003,
    )
    root = ConversationMessage(
        provider_event_id="root-event",
        conversation_identity=identity,
        message_id="1.000001",
        actor_id="alice",
        text="root",
        source_created_at="1.000001",
        source_order_at=1_000_001,
    )

    # WHEN
    waiting = repository.ingest(service.prepare(reply, MessageKind.REPLY, ActorKind.HUMAN))
    activated = repository.ingest(service.prepare(root, MessageKind.ROOT, ActorKind.HUMAN))
    turns = repository.turns(activated.conversation_id)

    # THEN
    assert waiting.disposition is EventDisposition.AWAITING_ROOT
    assert [turn.event_id for turn in turns] == ["root-event", "reply-event"]


def test_duplicate_and_event_identity_conflict_never_create_more_work(
    repository: CoordinatorRepository, service: CoordinatorService
) -> None:
    # GIVEN
    identity = ConversationIdentity(provider="chat", workspace="w", channel="c", thread="1.000001")
    message = ConversationMessage(
        provider_event_id="event",
        conversation_identity=identity,
        message_id="1.000001",
        actor_id="alice",
        text="root",
        source_created_at="1.000001",
        source_order_at=1_000_001,
    )
    repository.ingest(service.prepare(message, MessageKind.ROOT, ActorKind.HUMAN))

    # WHEN
    duplicate = repository.ingest(service.prepare(message, MessageKind.ROOT, ActorKind.HUMAN))
    conflict = repository.ingest(
        service.prepare(message.model_copy(update={"text": "changed"}), MessageKind.ROOT, ActorKind.HUMAN)
    )

    # THEN
    assert duplicate.disposition is EventDisposition.DUPLICATE
    assert conflict.disposition is EventDisposition.IDENTITY_CONFLICT
    assert len(repository.turns(1)) == 1


def test_same_provider_message_id_in_different_threads_creates_distinct_work(
    repository: CoordinatorRepository, service: CoordinatorService
) -> None:
    # GIVEN
    first = ConversationMessage(
        provider_event_id="first-event",
        conversation_identity=ConversationIdentity(provider="chat", workspace="w", channel="c", thread="first"),
        message_id="provider-message",
        actor_id="alice",
        text="first root",
        source_created_at="1.000001",
        source_order_at=1_000_001,
    )
    second = first.model_copy(
        update={
            "provider_event_id": "second-event",
            "conversation_identity": first.conversation_identity.model_copy(update={"thread": "second"}),
            "text": "second root",
        }
    )

    # WHEN
    first_result = repository.ingest(service.prepare(first, MessageKind.ROOT, ActorKind.HUMAN))
    second_result = repository.ingest(service.prepare(second, MessageKind.ROOT, ActorKind.HUMAN))

    # THEN
    assert first_result.disposition is EventDisposition.ACCEPTED
    assert second_result.disposition is EventDisposition.ACCEPTED
    assert first_result.conversation_id != second_result.conversation_id


def test_unsupported_file_only_message_is_durably_ignored_without_a_conversation(
    repository: CoordinatorRepository, service: CoordinatorService
) -> None:
    # GIVEN
    message = ConversationMessage(
        provider_event_id="file-event",
        conversation_identity=ConversationIdentity(provider="chat", workspace="w", channel="c", thread="root"),
        message_id="1.000001",
        actor_id="alice",
        text="",
        source_created_at="1.000001",
        source_order_at=1_000_001,
    )

    # WHEN
    result = repository.ingest(service.prepare(message, MessageKind.UNSUPPORTED, ActorKind.HUMAN))

    # THEN
    assert result.disposition is EventDisposition.IGNORED
    assert result.conversation_id == 0


def test_claiming_blocks_a_later_turn_while_an_earlier_turn_waits_for_retry(
    repository: CoordinatorRepository, service: CoordinatorService
) -> None:
    # GIVEN
    identity = ConversationIdentity(provider="chat", workspace="w", channel="c", thread="1.000001")
    for event_id, timestamp, kind in (
        ("root", "1.000001", MessageKind.ROOT),
        ("reply", "1.000002", MessageKind.REPLY),
    ):
        message = ConversationMessage(
            provider_event_id=event_id,
            conversation_identity=identity,
            message_id=timestamp,
            actor_id="alice",
            text=event_id,
            source_created_at=timestamp,
            source_order_at=1_000_000 + int(timestamp[-1]),
        )
        repository.ingest(service.prepare(message, kind, ActorKind.HUMAN))
    first = repository.claim_turn("9999-01-01T00:00:00+00:00")
    assert first is not None
    repository.schedule_retry(first.id, "9999-01-01T00:00:00+00:00", "later")

    # WHEN
    blocked = repository.claim_turn("2026-01-01T00:00:00+00:00")

    # THEN
    assert first.state is TurnState.SESSION_READY
    assert blocked is None


def test_orphan_reply_expires_without_creating_opencode_work(
    repository: CoordinatorRepository, service: CoordinatorService
) -> None:
    # GIVEN
    message = ConversationMessage(
        provider_event_id="orphan",
        conversation_identity=ConversationIdentity(provider="chat", workspace="w", channel="c", thread="root"),
        message_id="1.000002",
        actor_id="alice",
        text="reply",
        source_created_at="1.000002",
        source_order_at=1_000_002,
    )
    waiting = repository.ingest(service.prepare(message, MessageKind.REPLY, ActorKind.HUMAN))

    # WHEN
    count = repository.expire_orphans("9999-01-01T00:00:00+00:00")

    # THEN
    assert count == 1
    assert repository.conversation(waiting.conversation_id).state is ConversationState.EXPIRED
    assert repository.claim_turn("9999-01-01T00:00:00+00:00") is None


def test_replies_after_orphan_expiry_remain_durably_expired(
    repository: CoordinatorRepository, service: CoordinatorService
) -> None:
    # GIVEN
    identity = ConversationIdentity(provider="chat", workspace="w", channel="c", thread="missing-root")
    first = ConversationMessage(
        provider_event_id="first-orphan",
        conversation_identity=identity,
        message_id="reply-1",
        actor_id="alice",
        text="first reply",
        source_created_at="1.000001",
        source_order_at=1_000_001,
    )
    waiting = repository.ingest(service.prepare(first, MessageKind.REPLY, ActorKind.HUMAN))
    assert repository.expire_orphans("9999-01-01T00:00:00+00:00") == 1
    second = first.model_copy(
        update={
            "provider_event_id": "second-orphan",
            "message_id": "reply-2",
            "text": "second reply",
            "source_created_at": "1.000002",
            "source_order_at": 1_000_002,
        }
    )

    # WHEN
    expired = repository.ingest(service.prepare(second, MessageKind.REPLY, ActorKind.HUMAN))
    repeated_expiry = repository.expire_orphans("9999-01-01T00:00:00+00:00")
    duplicate = repository.ingest(service.prepare(second, MessageKind.REPLY, ActorKind.HUMAN))

    # THEN
    assert expired.disposition is EventDisposition.EXPIRED
    assert expired.conversation_id == waiting.conversation_id
    assert repeated_expiry == 0
    assert duplicate.disposition is EventDisposition.DUPLICATE
    assert repository.conversation(waiting.conversation_id).state is ConversationState.EXPIRED
    assert repository.claim_turn("9999-01-01T00:00:00+00:00") is None


def test_deferred_delivery_chunk_cannot_be_overtaken(
    repository: CoordinatorRepository, service: CoordinatorService
) -> None:
    # GIVEN
    message = ConversationMessage(
        provider_event_id="root",
        conversation_identity=ConversationIdentity(provider="chat", workspace="w", channel="c", thread="1.000001"),
        message_id="1.000001",
        actor_id="alice",
        text="root",
        source_created_at="1.000001",
        source_order_at=1_000_001,
    )
    ingested = repository.ingest(service.prepare(message, MessageKind.ROOT, ActorKind.HUMAN))
    turn = repository.claim_turn("9999-01-01T00:00:00+00:00")
    assert turn is not None
    repository.mark_prompt_intended(turn.id)
    repository.store_response(turn.id, "assistant", "firstsecond")
    repository.create_deliveries(
        turn.id,
        (
            ResponseChunk(index=1, count=2, text="[1/2] first", payload="first"),
            ResponseChunk(index=2, count=2, text="[2/2] second", payload="second"),
        ),
    )
    repository.schedule_delivery_retry(turn.id, 1, "9999-01-01T00:00:00+00:00")

    # WHEN
    next_chunk = repository.next_delivery(ingested.turn_ids[0], "2026-01-01T00:00:00+00:00")

    # THEN
    assert next_chunk is None
