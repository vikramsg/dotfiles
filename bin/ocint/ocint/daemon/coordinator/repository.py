from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import Engine, and_, exists, insert, or_, select, update
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.sql.elements import ColumnElement

from ocint.daemon.coordinator.models import (
    AuthorizationDecision,
    Conversation,
    ConversationIdentity,
    ConversationState,
    Delivery,
    DeliveryState,
    EventDisposition,
    IngestResult,
    MessageKind,
    PreparedMessage,
    ResponseChunk,
    Turn,
    TurnState,
)
from ocint.daemon.db.schema import (
    coordinator_conversation,
    coordinator_delivery,
    coordinator_event,
    coordinator_turn,
)


class CoordinatorRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def ingest(self, prepared: PreparedMessage) -> IngestResult:
        with self._immediate_transaction() as connection:
            existing = (
                connection.execute(
                    select(coordinator_event).where(coordinator_event.c.event_id == prepared.message.provider_event_id)
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                return self._existing_event(connection, existing, prepared)
            same_message = (
                connection.execute(select(coordinator_event).where(*self._message_identity(prepared)))
                .mappings()
                .one_or_none()
            )
            if same_message is not None:
                if self._same_immutable_message(same_message, prepared):
                    return IngestResult(disposition=EventDisposition.DUPLICATE)
                connection.execute(
                    update(coordinator_event)
                    .where(coordinator_event.c.event_id == same_message["event_id"])
                    .values(disposition=EventDisposition.IDENTITY_CONFLICT.value)
                )
                return IngestResult(disposition=EventDisposition.IDENTITY_CONFLICT)

            now = self._now()
            ignored = (
                prepared.kind is MessageKind.UNSUPPORTED or prepared.decision is AuthorizationDecision.UNAUTHORIZED
            )
            initial_disposition = EventDisposition.IGNORED if ignored else EventDisposition.AWAITING_ROOT
            self._insert_event(connection, prepared, initial_disposition, now)
            if ignored:
                return IngestResult(disposition=EventDisposition.IGNORED)

            conversation_row = self._conversation_for(connection, prepared.message.conversation_identity)
            if conversation_row is None:
                conversation_id = int(
                    connection.execute(
                        insert(coordinator_conversation)
                        .returning(coordinator_conversation.c.id)
                        .values(
                            provider=prepared.message.conversation_identity.provider,
                            workspace_id=prepared.message.conversation_identity.workspace,
                            channel_id=prepared.message.conversation_identity.channel,
                            thread_id=prepared.message.conversation_identity.thread,
                            state=ConversationState.AWAITING_ROOT.value,
                            opencode_session_id="",
                            created_at=now,
                            updated_at=now,
                        )
                    ).scalar_one()
                )
                conversation_state = ConversationState.AWAITING_ROOT
            else:
                conversation_id = int(conversation_row["id"])
                conversation_state = ConversationState(str(conversation_row["state"]))

            if conversation_state is ConversationState.EXPIRED:
                connection.execute(
                    update(coordinator_event)
                    .where(coordinator_event.c.event_id == prepared.message.provider_event_id)
                    .values(disposition=EventDisposition.EXPIRED.value)
                )
                return IngestResult(
                    disposition=EventDisposition.EXPIRED,
                    conversation_id=conversation_id,
                )

            if prepared.kind is MessageKind.ROOT:
                connection.execute(
                    update(coordinator_conversation)
                    .where(coordinator_conversation.c.id == conversation_id)
                    .values(state=ConversationState.ACTIVE.value, updated_at=now)
                )
                connection.execute(
                    update(coordinator_event)
                    .where(*self._conversation_event_identity(prepared.message.conversation_identity))
                    .where(
                        coordinator_event.c.disposition.in_(
                            (EventDisposition.AWAITING_ROOT.value, EventDisposition.ACCEPTED.value)
                        )
                    )
                    .values(disposition=EventDisposition.ACCEPTED.value)
                )
                turn_ids = self._create_missing_turns(connection, conversation_id, now)
                return IngestResult(
                    disposition=EventDisposition.ACCEPTED,
                    conversation_id=conversation_id,
                    turn_ids=turn_ids,
                )

            if conversation_state is ConversationState.ACTIVE:
                connection.execute(
                    update(coordinator_event)
                    .where(coordinator_event.c.event_id == prepared.message.provider_event_id)
                    .values(disposition=EventDisposition.ACCEPTED.value)
                )
                turn_ids = self._create_missing_turns(connection, conversation_id, now)
                return IngestResult(
                    disposition=EventDisposition.ACCEPTED,
                    conversation_id=conversation_id,
                    turn_ids=turn_ids,
                )
            return IngestResult(
                disposition=EventDisposition.AWAITING_ROOT,
                conversation_id=conversation_id,
            )

    def expire_orphans(self, created_before: str) -> int:
        with self.engine.begin() as connection:
            rows = tuple(
                connection.execute(
                    select(coordinator_conversation.c.id).where(
                        coordinator_conversation.c.state == ConversationState.AWAITING_ROOT.value,
                        coordinator_conversation.c.created_at < created_before,
                    )
                ).scalars()
            )
            if not rows:
                return 0
            now = self._now()
            connection.execute(
                update(coordinator_conversation)
                .where(coordinator_conversation.c.id.in_(rows))
                .values(state=ConversationState.EXPIRED.value, updated_at=now)
            )
            for conversation_id in rows:
                identity = (
                    connection.execute(
                        select(coordinator_conversation).where(coordinator_conversation.c.id == conversation_id)
                    )
                    .mappings()
                    .one()
                )
                connection.execute(
                    update(coordinator_event)
                    .where(
                        coordinator_event.c.provider == identity["provider"],
                        coordinator_event.c.workspace_id == identity["workspace_id"],
                        coordinator_event.c.channel_id == identity["channel_id"],
                        coordinator_event.c.thread_id == identity["thread_id"],
                        coordinator_event.c.disposition == EventDisposition.AWAITING_ROOT.value,
                    )
                    .values(disposition=EventDisposition.EXPIRED.value)
                )
            return len(rows)

    def claim_turn(self, ready_at: str) -> Turn | None:
        terminal = (TurnState.COMPLETED.value, TurnState.FAILED.value, TurnState.IGNORED.value)
        earlier = coordinator_turn.alias("earlier_coordinator_turn")
        earlier_order = or_(
            earlier.c.source_order_at < coordinator_turn.c.source_order_at,
            and_(
                earlier.c.source_order_at == coordinator_turn.c.source_order_at,
                earlier.c.source_order_tiebreaker < coordinator_turn.c.source_order_tiebreaker,
            ),
        )
        with self._immediate_transaction() as connection:
            row = (
                connection.execute(
                    select(coordinator_turn)
                    .join(
                        coordinator_conversation,
                        coordinator_conversation.c.id == coordinator_turn.c.conversation_id,
                    )
                    .where(
                        coordinator_conversation.c.state == ConversationState.ACTIVE.value,
                        coordinator_turn.c.state.not_in(terminal),
                        or_(
                            coordinator_turn.c.retry_not_before == "",
                            coordinator_turn.c.retry_not_before <= ready_at,
                        ),
                        ~exists(
                            select(earlier.c.id).where(
                                earlier.c.conversation_id == coordinator_turn.c.conversation_id,
                                earlier_order,
                                earlier.c.state.not_in(terminal),
                            )
                        ),
                    )
                    .order_by(coordinator_turn.c.source_order_at, coordinator_turn.c.source_order_tiebreaker)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            if TurnState(str(row["state"])) is TurnState.RECEIVED:
                changed = connection.execute(
                    update(coordinator_turn)
                    .where(
                        coordinator_turn.c.id == row["id"],
                        coordinator_turn.c.state == TurnState.RECEIVED.value,
                    )
                    .values(state=TurnState.SESSION_READY.value, updated_at=self._now())
                )
                if changed.rowcount != 1:
                    return None
                row = (
                    connection.execute(select(coordinator_turn).where(coordinator_turn.c.id == row["id"]))
                    .mappings()
                    .one()
                )
            return self._turn(row)

    def conversation(self, conversation_id: int) -> Conversation:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(coordinator_conversation).where(coordinator_conversation.c.id == conversation_id)
                )
                .mappings()
                .one()
            )
        return self._conversation(row)

    def turn(self, turn_id: int) -> Turn:
        with self.engine.connect() as connection:
            row = connection.execute(select(coordinator_turn).where(coordinator_turn.c.id == turn_id)).mappings().one()
        return self._turn(row)

    def turns(self, conversation_id: int) -> tuple[Turn, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(coordinator_turn)
                .where(coordinator_turn.c.conversation_id == conversation_id)
                .order_by(coordinator_turn.c.source_order_at, coordinator_turn.c.source_order_tiebreaker)
            ).mappings()
            return tuple(self._turn(row) for row in rows)

    def set_session(self, conversation_id: int, session_id: str) -> Conversation:
        if not session_id:
            raise ValueError("session ID must not be empty")
        with self.engine.begin() as connection:
            connection.execute(
                update(coordinator_conversation)
                .where(
                    coordinator_conversation.c.id == conversation_id,
                    coordinator_conversation.c.opencode_session_id == "",
                )
                .values(opencode_session_id=session_id, updated_at=self._now())
            )
        return self.conversation(conversation_id)

    def mark_prompt_intended(self, turn_id: int) -> Turn:
        self._transition(turn_id, TurnState.SESSION_READY, TurnState.PROMPT_INTENDED)
        return self.turn(turn_id)

    def mark_prompt_submitted(self, turn_id: int) -> Turn:
        with self.engine.begin() as connection:
            connection.execute(
                update(coordinator_turn)
                .where(
                    coordinator_turn.c.id == turn_id,
                    coordinator_turn.c.state.in_((TurnState.PROMPT_INTENDED.value, TurnState.PROMPT_SUBMITTED.value)),
                )
                .values(state=TurnState.PROMPT_SUBMITTED.value, retry_not_before="", updated_at=self._now())
            )
        return self.turn(turn_id)

    def store_response(self, turn_id: int, assistant_message_id: str, response_text: str) -> Turn:
        if not assistant_message_id:
            raise ValueError("assistant message ID must not be empty")
        with self.engine.begin() as connection:
            connection.execute(
                update(coordinator_turn)
                .where(
                    coordinator_turn.c.id == turn_id,
                    coordinator_turn.c.state.in_(
                        (
                            TurnState.PROMPT_INTENDED.value,
                            TurnState.PROMPT_SUBMITTED.value,
                            TurnState.RESPONSE_READY.value,
                        )
                    ),
                )
                .values(
                    state=TurnState.RESPONSE_READY.value,
                    assistant_message_id=assistant_message_id,
                    response_text=response_text,
                    error="",
                    retry_not_before="",
                    updated_at=self._now(),
                )
            )
        return self.turn(turn_id)

    def store_failure_response(self, turn_id: int, error: str, safe_response: str) -> Turn:
        with self.engine.begin() as connection:
            connection.execute(
                update(coordinator_turn)
                .where(coordinator_turn.c.id == turn_id, coordinator_turn.c.state.not_in(self._terminal_states()))
                .values(
                    state=TurnState.RESPONSE_READY.value,
                    response_text=safe_response,
                    error=error,
                    retry_not_before="",
                    updated_at=self._now(),
                )
            )
        return self.turn(turn_id)

    def schedule_retry(self, turn_id: int, retry_not_before: str, error: str) -> Turn:
        with self.engine.begin() as connection:
            connection.execute(
                update(coordinator_turn)
                .where(coordinator_turn.c.id == turn_id, coordinator_turn.c.state.not_in(self._terminal_states()))
                .values(
                    retry_count=coordinator_turn.c.retry_count + 1,
                    retry_not_before=retry_not_before,
                    error=error,
                    updated_at=self._now(),
                )
            )
        return self.turn(turn_id)

    def create_deliveries(self, turn_id: int, chunks: tuple[ResponseChunk, ...]) -> tuple[Delivery, ...]:
        if not chunks:
            raise ValueError("delivery requires at least one response chunk")
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(coordinator_delivery).where(coordinator_delivery.c.turn_id == turn_id)
            ).first()
            if existing is None:
                now = self._now()
                for chunk in chunks:
                    client_message_id = str(uuid5(NAMESPACE_URL, f"ocint-coordinator-delivery:{turn_id}:{chunk.index}"))
                    connection.execute(
                        insert(coordinator_delivery).values(
                            turn_id=turn_id,
                            chunk_index=chunk.index,
                            client_msg_id=client_message_id,
                            text=chunk.text,
                            state=DeliveryState.PENDING.value,
                            provider_message_id="",
                            retry_count=0,
                            retry_not_before="",
                            created_at=now,
                            updated_at=now,
                        )
                    )
                connection.execute(
                    update(coordinator_turn)
                    .where(
                        coordinator_turn.c.id == turn_id,
                        coordinator_turn.c.state == TurnState.RESPONSE_READY.value,
                    )
                    .values(state=TurnState.DELIVERING.value, updated_at=now)
                )
        return self.deliveries(turn_id)

    def deliveries(self, turn_id: int) -> tuple[Delivery, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(coordinator_delivery)
                .where(coordinator_delivery.c.turn_id == turn_id)
                .order_by(coordinator_delivery.c.chunk_index)
            ).mappings()
            return tuple(self._delivery(row) for row in rows)

    def next_delivery(self, turn_id: int, ready_at: str) -> Delivery | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(coordinator_delivery)
                    .where(
                        coordinator_delivery.c.turn_id == turn_id,
                        coordinator_delivery.c.state != DeliveryState.DELIVERED.value,
                    )
                    .order_by(coordinator_delivery.c.chunk_index)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        retry_not_before = str(row["retry_not_before"])
        if retry_not_before and retry_not_before > ready_at:
            return None
        return self._delivery(row)

    def mark_delivery_intended(self, turn_id: int, chunk_index: int) -> Delivery:
        with self.engine.begin() as connection:
            connection.execute(
                update(coordinator_delivery)
                .where(
                    coordinator_delivery.c.turn_id == turn_id,
                    coordinator_delivery.c.chunk_index == chunk_index,
                    coordinator_delivery.c.state == DeliveryState.PENDING.value,
                )
                .values(state=DeliveryState.INTENDED.value, updated_at=self._now())
            )
        return self._delivery_by_id(turn_id, chunk_index)

    def mark_delivered(self, turn_id: int, chunk_index: int, provider_message_id: str) -> Delivery:
        if not provider_message_id:
            raise ValueError("provider message ID must not be empty")
        with self.engine.begin() as connection:
            connection.execute(
                update(coordinator_delivery)
                .where(
                    coordinator_delivery.c.turn_id == turn_id,
                    coordinator_delivery.c.chunk_index == chunk_index,
                )
                .values(
                    state=DeliveryState.DELIVERED.value,
                    provider_message_id=provider_message_id,
                    retry_not_before="",
                    updated_at=self._now(),
                )
            )
        return self._delivery_by_id(turn_id, chunk_index)

    def schedule_delivery_retry(self, turn_id: int, chunk_index: int, retry_not_before: str) -> Delivery:
        with self.engine.begin() as connection:
            connection.execute(
                update(coordinator_delivery)
                .where(
                    coordinator_delivery.c.turn_id == turn_id,
                    coordinator_delivery.c.chunk_index == chunk_index,
                )
                .values(
                    retry_count=coordinator_delivery.c.retry_count + 1,
                    retry_not_before=retry_not_before,
                    updated_at=self._now(),
                )
            )
        return self._delivery_by_id(turn_id, chunk_index)

    def complete_turn(self, turn_id: int) -> Turn:
        with self.engine.begin() as connection:
            undelivered = connection.execute(
                select(
                    exists().where(
                        coordinator_delivery.c.turn_id == turn_id,
                        coordinator_delivery.c.state != DeliveryState.DELIVERED.value,
                    )
                )
            ).scalar_one()
            if undelivered:
                raise ValueError(f"turn {turn_id} still has undelivered chunks")
            stored = connection.execute(
                select(coordinator_turn.c.error).where(coordinator_turn.c.id == turn_id)
            ).scalar_one()
            connection.execute(
                update(coordinator_turn)
                .where(
                    coordinator_turn.c.id == turn_id,
                    coordinator_turn.c.state == TurnState.DELIVERING.value,
                )
                .values(
                    state=TurnState.FAILED.value if str(stored) else TurnState.COMPLETED.value,
                    updated_at=self._now(),
                )
            )
        return self.turn(turn_id)

    def _existing_event(self, connection: Connection, existing: RowMapping, prepared: PreparedMessage) -> IngestResult:
        if self._same_immutable_message(existing, prepared):
            return IngestResult(disposition=EventDisposition.DUPLICATE)
        connection.execute(
            update(coordinator_event)
            .where(coordinator_event.c.event_id == prepared.message.provider_event_id)
            .values(disposition=EventDisposition.IDENTITY_CONFLICT.value)
        )
        return IngestResult(disposition=EventDisposition.IDENTITY_CONFLICT)

    @staticmethod
    def _same_immutable_message(row: RowMapping, prepared: PreparedMessage) -> bool:
        message = prepared.message
        identity = message.conversation_identity
        return (
            str(row["provider"]) == identity.provider
            and str(row["workspace_id"]) == identity.workspace
            and str(row["channel_id"]) == identity.channel
            and str(row["thread_id"]) == identity.thread
            and str(row["message_id"]) == message.message_id
            and str(row["actor_id"]) == message.actor_id
            and str(row["text"]) == message.text
            and str(row["source_created_at"]) == message.source_created_at
            and int(row["source_order_at"]) == message.source_order_at
        )

    @staticmethod
    def _message_identity(prepared: PreparedMessage) -> tuple[ColumnElement[bool], ...]:
        message = prepared.message
        identity = message.conversation_identity
        return (
            coordinator_event.c.provider == identity.provider,
            coordinator_event.c.workspace_id == identity.workspace,
            coordinator_event.c.channel_id == identity.channel,
            coordinator_event.c.thread_id == identity.thread,
            coordinator_event.c.message_id == message.message_id,
        )

    @staticmethod
    def _conversation_event_identity(identity: ConversationIdentity) -> tuple[ColumnElement[bool], ...]:
        return (
            coordinator_event.c.provider == identity.provider,
            coordinator_event.c.workspace_id == identity.workspace,
            coordinator_event.c.channel_id == identity.channel,
            coordinator_event.c.thread_id == identity.thread,
        )

    @staticmethod
    def _conversation_for(connection: Connection, identity: ConversationIdentity) -> RowMapping | None:
        return (
            connection.execute(
                select(coordinator_conversation).where(
                    coordinator_conversation.c.provider == identity.provider,
                    coordinator_conversation.c.workspace_id == identity.workspace,
                    coordinator_conversation.c.channel_id == identity.channel,
                    coordinator_conversation.c.thread_id == identity.thread,
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _insert_event(
        connection: Connection,
        prepared: PreparedMessage,
        disposition: EventDisposition,
        now: str,
    ) -> None:
        message = prepared.message
        identity = message.conversation_identity
        connection.execute(
            insert(coordinator_event).values(
                event_id=message.provider_event_id,
                provider=identity.provider,
                workspace_id=identity.workspace,
                channel_id=identity.channel,
                thread_id=identity.thread,
                message_id=message.message_id,
                actor_id=message.actor_id,
                text=message.text,
                source_created_at=message.source_created_at,
                source_order_at=message.source_order_at,
                message_kind=prepared.kind.value,
                managed_prompt=prepared.managed_prompt,
                disposition=disposition.value,
                created_at=now,
            )
        )

    @staticmethod
    def _create_missing_turns(connection: Connection, conversation_id: int, now: str) -> tuple[int, ...]:
        events = connection.execute(
            select(coordinator_event)
            .join(
                coordinator_conversation,
                and_(
                    coordinator_conversation.c.provider == coordinator_event.c.provider,
                    coordinator_conversation.c.workspace_id == coordinator_event.c.workspace_id,
                    coordinator_conversation.c.channel_id == coordinator_event.c.channel_id,
                    coordinator_conversation.c.thread_id == coordinator_event.c.thread_id,
                ),
            )
            .where(
                coordinator_conversation.c.id == conversation_id,
                coordinator_event.c.disposition == EventDisposition.ACCEPTED.value,
                ~exists().where(coordinator_turn.c.event_id == coordinator_event.c.event_id),
            )
            .order_by(coordinator_event.c.source_order_at, coordinator_event.c.message_id)
        ).mappings()
        identifiers: list[int] = []
        for event in events:
            identifier = int(
                connection.execute(
                    insert(coordinator_turn)
                    .returning(coordinator_turn.c.id)
                    .values(
                        event_id=event["event_id"],
                        conversation_id=conversation_id,
                        source_order_at=event["source_order_at"],
                        source_order_tiebreaker=event["message_id"],
                        state=TurnState.RECEIVED.value,
                        managed_prompt=event["managed_prompt"],
                        opencode_user_message_id="msg_"
                        + str(uuid5(NAMESPACE_URL, f"ocint-coordinator-user-message:{event['event_id']}")),
                        assistant_message_id="",
                        response_text="",
                        error="",
                        retry_count=0,
                        retry_not_before="",
                        created_at=now,
                        updated_at=now,
                    )
                ).scalar_one()
            )
            identifiers.append(identifier)
        return tuple(identifiers)

    def _transition(self, turn_id: int, expected: TurnState, target: TurnState) -> None:
        with self.engine.begin() as connection:
            changed = connection.execute(
                update(coordinator_turn)
                .where(coordinator_turn.c.id == turn_id, coordinator_turn.c.state == expected.value)
                .values(state=target.value, retry_not_before="", updated_at=self._now())
            )
            if changed.rowcount != 1:
                current = connection.execute(
                    select(coordinator_turn.c.state).where(coordinator_turn.c.id == turn_id)
                ).scalar_one()
                if str(current) != target.value:
                    raise ValueError(f"turn {turn_id} cannot move from {current} to {target.value}")

    def _delivery_by_id(self, turn_id: int, chunk_index: int) -> Delivery:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(coordinator_delivery).where(
                        coordinator_delivery.c.turn_id == turn_id,
                        coordinator_delivery.c.chunk_index == chunk_index,
                    )
                )
                .mappings()
                .one()
            )
        return self._delivery(row)

    @staticmethod
    def _terminal_states() -> tuple[str, ...]:
        return (TurnState.COMPLETED.value, TurnState.FAILED.value, TurnState.IGNORED.value)

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @contextmanager
    def _immediate_transaction(self) -> Iterator[Connection]:
        connection = self.engine.connect()
        try:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _conversation(row: RowMapping) -> Conversation:
        return Conversation(
            id=int(row["id"]),
            identity=ConversationIdentity(
                provider=str(row["provider"]),
                workspace=str(row["workspace_id"]),
                channel=str(row["channel_id"]),
                thread=str(row["thread_id"]),
            ),
            state=ConversationState(str(row["state"])),
            opencode_session_id=str(row["opencode_session_id"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _turn(row: RowMapping) -> Turn:
        return Turn(
            id=int(row["id"]),
            event_id=str(row["event_id"]),
            conversation_id=int(row["conversation_id"]),
            source_order_at=int(row["source_order_at"]),
            source_order_tiebreaker=str(row["source_order_tiebreaker"]),
            state=TurnState(str(row["state"])),
            managed_prompt=str(row["managed_prompt"]),
            opencode_user_message_id=str(row["opencode_user_message_id"]),
            assistant_message_id=str(row["assistant_message_id"]),
            response_text=str(row["response_text"]),
            error=str(row["error"]),
            retry_count=int(row["retry_count"]),
            retry_not_before=str(row["retry_not_before"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _delivery(row: RowMapping) -> Delivery:
        return Delivery(
            turn_id=int(row["turn_id"]),
            chunk_index=int(row["chunk_index"]),
            client_msg_id=str(row["client_msg_id"]),
            text=str(row["text"]),
            state=DeliveryState(str(row["state"])),
            provider_message_id=str(row["provider_message_id"]),
            retry_count=int(row["retry_count"]),
            retry_not_before=str(row["retry_not_before"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
