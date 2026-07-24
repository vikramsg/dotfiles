from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import Engine, Select, and_, exists, insert, or_, select, update
from sqlalchemy.engine import Connection, RowMapping

from ocint.daemon.db.schema import job, task, task_job, task_message, thread, thread_message
from ocint.daemon.models import GitHubLogin, JobState, MessageClassification
from ocint.daemon.tasks.models import (
    FailedTaskClaim,
    FailedTaskRetry,
    RetryAttachment,
    SuccessorCreated,
    SuccessorExisting,
    SuccessorUnavailable,
    Task,
    TaskKind,
    TaskReason,
    TaskState,
    Thread,
    ThreadMessage,
)


class TaskRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def upsert_thread(
        self,
        source_id: str,
        title: str | None,
        configured_repository: str = "",
        eligible: bool = False,
    ) -> Thread:
        with self.engine.begin() as connection:
            row = connection.execute(select(thread).where(thread.c.source_id == source_id)).mappings().one_or_none()
            if row is None:
                connection.execute(
                    insert(thread).values(
                        source_id=source_id,
                        configured_repository=configured_repository,
                        eligible=eligible,
                        title=title,
                    )
                )
            else:
                resolved_title = title if title else row["title"]
                connection.execute(
                    update(thread)
                    .where(thread.c.id == row["id"])
                    .values(configured_repository=configured_repository, eligible=eligible, title=resolved_title)
                )
            row = connection.execute(select(thread).where(thread.c.source_id == source_id)).mappings().one()
        return self._thread(row)

    def upsert_message(
        self,
        thread_id: int,
        source_id: str,
        actor: GitHubLogin | str,
        classification: MessageClassification,
        body: str,
        source_created_at: str,
    ) -> ThreadMessage:
        with self.engine.begin() as connection:
            identity = thread_message.c.source_id == source_id
            row = connection.execute(select(thread_message).where(identity)).mappings().one_or_none()
            now = datetime.now(UTC).isoformat()
            if row is not None and int(row["thread_id"]) != thread_id:
                raise ValueError(f"message source ID already belongs to thread {row['thread_id']}: {source_id}")
            if row is None:
                connection.execute(
                    insert(thread_message).values(
                        thread_id=thread_id,
                        source_id=source_id,
                        actor=str(actor),
                        classification=classification.value,
                        body=body,
                        source_created_at=source_created_at,
                        created_at=now,
                        updated_at=now,
                    )
                )
            elif not self._covered_by_addressed(connection, int(row["id"])):
                connection.execute(
                    update(thread_message)
                    .where(thread_message.c.id == row["id"])
                    .values(
                        actor=str(actor),
                        classification=classification.value,
                        body=body,
                        source_created_at=source_created_at,
                        updated_at=now,
                    )
                )
            row = connection.execute(select(thread_message).where(identity)).mappings().one()
        return self._message(row)

    def threads(self) -> tuple[Thread, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(thread).order_by(thread.c.id)).mappings()
            return tuple(self._thread(row) for row in rows)

    def thread(self, thread_id: int) -> Thread:
        with self.engine.connect() as connection:
            row = connection.execute(select(thread).where(thread.c.id == thread_id)).mappings().one()
        return self._thread(row)

    def messages(self, thread_id: int) -> tuple[ThreadMessage, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(thread_message)
                .where(thread_message.c.thread_id == thread_id)
                .order_by(thread_message.c.source_created_at, thread_message.c.source_id)
            ).mappings()
            return tuple(self._message(row) for row in rows)

    def actionable_messages(self, thread_id: int) -> tuple[ThreadMessage, ...]:
        return tuple(
            message
            for message in self.messages(thread_id)
            if message.classification is MessageClassification.ACTIONABLE
        )

    def task_messages(self, task_id: int) -> tuple[ThreadMessage, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(thread_message)
                .join(task_message, task_message.c.message_id == thread_message.c.id)
                .where(task_message.c.task_id == task_id)
                .order_by(thread_message.c.source_created_at, thread_message.c.source_id)
            ).mappings()
            return tuple(self._message(row) for row in rows)

    def pending_messages(self, thread_id: int) -> tuple[ThreadMessage, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(self._pending_query(thread_id)).mappings()
            return tuple(self._message(row) for row in rows)

    def unresolved(self, thread_id: int) -> Task | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(task)
                    .where(task.c.thread_id == thread_id, task.c.state == TaskState.UNRESOLVED.value)
                    .order_by(task.c.id.desc())
                )
                .mappings()
                .first()
            )
        return self._task(row) if row is not None else None

    def latest(self, thread_id: int) -> Task | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(select(task).where(task.c.thread_id == thread_id).order_by(task.c.id.desc()))
                .mappings()
                .first()
            )
        return self._task(row) if row is not None else None

    def create_pending(self, thread_id: int, kind: TaskKind, predecessor_task_id: int) -> Task | None:
        with self._claim_transaction() as connection:
            messages = tuple(connection.execute(self._pending_query(thread_id)).mappings())
            if not messages:
                return None
            task_id = self._insert_task(connection, thread_id, kind, predecessor_task_id, messages)
        return self.get(task_id)

    def claim_failed(self, current: Task, reason: str) -> FailedTaskClaim:
        with self._claim_transaction() as connection:
            row = connection.execute(select(task).where(task.c.id == current.id)).mappings().one()
            if TaskState(str(row["state"])) is not TaskState.UNRESOLVED:
                successor = self._successor(connection, current.id)
                return (
                    SuccessorExisting(task=self._task(successor)) if successor is not None else SuccessorUnavailable()
                )
            latest_attempt = int(
                connection.execute(
                    select(task_job.c.attempt)
                    .where(task_job.c.task_id == current.id)
                    .order_by(task_job.c.attempt.desc())
                )
                .scalars()
                .first()
                or 0
            )
            claimed_attempt = int(row["retry_claim_attempt"])
            if claimed_attempt > latest_attempt:
                return FailedTaskRetry(task=self._task(row), attempt=claimed_attempt)
            pending = tuple(connection.execute(self._pending_query(current.thread_id)).mappings())
            if pending:
                transitioned = connection.execute(
                    update(task)
                    .where(
                        task.c.id == current.id,
                        task.c.state == TaskState.UNRESOLVED.value,
                        task.c.retry_claim_attempt == claimed_attempt,
                    )
                    .values(state=TaskState.SKIPPED.value, reason=reason, updated_at=datetime.now(UTC).isoformat())
                )
                if transitioned.rowcount != 1:
                    return SuccessorUnavailable()
                messages = tuple(connection.execute(self._pending_query(current.thread_id)).mappings())
                if not messages:
                    return SuccessorUnavailable()
                task_id = self._insert_task(connection, current.thread_id, TaskKind.FOLLOW_UP, current.id, messages)
                successor = connection.execute(select(task).where(task.c.id == task_id)).mappings().one()
                return SuccessorCreated(task=self._task(successor))
            attempt = latest_attempt + 1
            claimed = connection.execute(
                update(task)
                .where(
                    task.c.id == current.id,
                    task.c.state == TaskState.UNRESOLVED.value,
                    task.c.retry_claim_attempt == claimed_attempt,
                )
                .values(retry_claim_attempt=attempt, updated_at=datetime.now(UTC).isoformat())
            )
            if claimed.rowcount != 1:
                return SuccessorUnavailable()
            return FailedTaskRetry(task=self._task(row), attempt=attempt)

    def attach_claimed_job(self, task_id: int, attempt: int, job_id: str) -> RetryAttachment:
        with self._claim_transaction() as connection:
            row = connection.execute(select(task).where(task.c.id == task_id)).mappings().one()
            if TaskState(str(row["state"])) is not TaskState.UNRESOLVED or int(row["retry_claim_attempt"]) != attempt:
                return RetryAttachment.REJECTED
            existing = connection.execute(
                select(task_job.c.job_id).where(task_job.c.task_id == task_id, task_job.c.attempt == attempt)
            ).scalar_one_or_none()
            if existing is not None:
                return RetryAttachment.EXISTING
            connection.execute(insert(task_job).values(task_id=task_id, job_id=job_id, attempt=attempt))
            return RetryAttachment.ATTACHED

    def reusable_job_id(self, thread_id: int) -> str:
        with self.engine.connect() as connection:
            value = (
                connection.execute(
                    select(task_job.c.job_id)
                    .join(task, task.c.id == task_job.c.task_id)
                    .join(job, job.c.id == task_job.c.job_id)
                    .where(
                        task.c.thread_id == thread_id,
                        task.c.state == TaskState.ADDRESSED.value,
                        job.c.state == JobState.COMPLETED.value,
                    )
                    .order_by(task.c.id.desc(), task_job.c.attempt.desc())
                )
                .scalars()
                .first()
            )
        return str(value) if value is not None else ""

    def get(self, task_id: int) -> Task:
        with self.engine.connect() as connection:
            row = connection.execute(select(task).where(task.c.id == task_id)).mappings().one()
        return self._task(row)

    def set_state(self, task_id: int, state: TaskState, reason: str = "") -> Task:
        with self.engine.begin() as connection:
            connection.execute(
                update(task)
                .where(task.c.id == task_id)
                .values(state=state.value, reason=reason, updated_at=datetime.now(UTC).isoformat())
            )
        return self.get(task_id)

    def attach_job(self, task_id: int, job_id: str) -> None:
        with self.engine.begin() as connection:
            attempt = (
                connection.execute(
                    select(task_job.c.attempt).where(task_job.c.task_id == task_id).order_by(task_job.c.attempt.desc())
                )
                .scalars()
                .first()
            )
            connection.execute(insert(task_job).values(task_id=task_id, job_id=job_id, attempt=(attempt or 0) + 1))

    def latest_job_id(self, task_id: int) -> str:
        with self.engine.connect() as connection:
            value = (
                connection.execute(
                    select(task_job.c.job_id).where(task_job.c.task_id == task_id).order_by(task_job.c.attempt.desc())
                )
                .scalars()
                .first()
            )
        return str(value) if value is not None else ""

    def attempt_count(self, task_id: int) -> int:
        with self.engine.connect() as connection:
            value = (
                connection.execute(
                    select(task_job.c.attempt).where(task_job.c.task_id == task_id).order_by(task_job.c.attempt.desc())
                )
                .scalars()
                .first()
            )
        return int(value or 0)

    def task_for_job(self, job_id: str) -> Task | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(task).join(task_job, task_job.c.task_id == task.c.id).where(task_job.c.job_id == job_id)
                )
                .mappings()
                .one_or_none()
            )
        return self._task(row) if row is not None else None

    @staticmethod
    def _pending_query(thread_id: int) -> Select:
        covering = (
            select(task_message.c.message_id)
            .join(task, task.c.id == task_message.c.task_id)
            .where(
                or_(
                    task.c.state.in_((TaskState.ADDRESSED.value, TaskState.UNRESOLVED.value)),
                    and_(
                        task.c.state == TaskState.ERRORED.value,
                        task.c.reason == TaskReason.OWNED_PULL_REQUEST_CLOSED.value,
                    ),
                )
            )
        )
        return (
            select(thread_message)
            .where(
                thread_message.c.thread_id == thread_id,
                thread_message.c.classification == MessageClassification.ACTIONABLE.value,
                ~thread_message.c.id.in_(covering),
            )
            .order_by(thread_message.c.source_created_at, thread_message.c.source_id)
        )

    @contextmanager
    def _claim_transaction(self) -> Iterator[Connection]:
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
    def _covered_by_addressed(connection: Connection, message_id: int) -> bool:
        return bool(
            connection.execute(
                select(
                    exists().where(
                        task_message.c.message_id == message_id,
                        task.c.id == task_message.c.task_id,
                        task.c.state == TaskState.ADDRESSED.value,
                    )
                )
            ).scalar_one()
        )

    @staticmethod
    def _successor(connection: Connection, predecessor_task_id: int) -> RowMapping | None:
        return (
            connection.execute(
                select(task).where(task.c.predecessor_task_id == predecessor_task_id).order_by(task.c.id.desc())
            )
            .mappings()
            .first()
        )

    @staticmethod
    def _insert_task(
        connection: Connection,
        thread_id: int,
        kind: TaskKind,
        predecessor_task_id: int,
        messages: tuple[RowMapping, ...],
    ) -> int:
        if not messages:
            raise ValueError("task creation requires at least one message")
        now = datetime.now(UTC).isoformat()
        task_id = int(
            connection.execute(
                insert(task)
                .returning(task.c.id)
                .values(
                    thread_id=thread_id,
                    kind=kind.value,
                    state=TaskState.UNRESOLVED.value,
                    predecessor_task_id=predecessor_task_id,
                    retry_claim_attempt=0,
                    reason="",
                    created_at=now,
                    updated_at=now,
                )
            ).scalar_one()
        )
        for message in messages:
            connection.execute(insert(task_message).values(task_id=task_id, message_id=message["id"]))
        return task_id

    @staticmethod
    def _thread(row: RowMapping) -> Thread:
        return Thread(**{field: row[field] for field in Thread.model_fields})

    @staticmethod
    def _message(row: RowMapping) -> ThreadMessage:
        values = {field: row[field] for field in ThreadMessage.model_fields}
        values["actor"] = GitHubLogin(str(row["actor"]))
        return ThreadMessage(**values)

    @staticmethod
    def _task(row: RowMapping) -> Task:
        return Task(**{field: row[field] for field in Task.model_fields})
