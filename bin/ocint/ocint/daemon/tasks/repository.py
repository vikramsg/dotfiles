from datetime import UTC, datetime

from sqlalchemy import Engine, insert, select, update
from sqlalchemy.engine import RowMapping

from ocint.daemon.db.schema import job, task, task_job, task_message, thread, thread_message
from ocint.daemon.service import JobState
from ocint.daemon.tasks.models import (
    MessageActorType,
    MessageDisposition,
    Task,
    TaskKind,
    TaskState,
    Thread,
    ThreadMessage,
)


class TaskRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def upsert_thread(
        self, repository: str, source: str, source_thread_id: str, actor: str, title: str, body: str
    ) -> Thread:
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(thread).where(thread.c.source == source, thread.c.source_thread_id == source_thread_id)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                now = datetime.now(UTC).isoformat()
                connection.execute(
                    insert(thread).values(
                        repository=repository,
                        source=source,
                        source_thread_id=source_thread_id,
                        actor=actor,
                        eligible=1,
                        execution_job_id="",
                        title=title,
                        body=body,
                        created_at=now,
                        updated_at=now,
                    )
                )
                row = (
                    connection.execute(
                        select(thread).where(thread.c.source == source, thread.c.source_thread_id == source_thread_id)
                    )
                    .mappings()
                    .one()
                )
            else:
                connection.execute(
                    update(thread)
                    .where(thread.c.id == row["id"])
                    .values(actor=actor, eligible=1, title=title, body=body, updated_at=datetime.now(UTC).isoformat())
                )
                row = connection.execute(select(thread).where(thread.c.id == row["id"])).mappings().one()
        return self._thread(row)

    def synchronize_source(self, repository: str, source: str, source_thread_ids: tuple[str, ...]) -> None:
        with self.engine.begin() as connection:
            query = update(thread).where(thread.c.repository == repository, thread.c.source == source)
            if source_thread_ids:
                query = query.where(~thread.c.source_thread_id.in_(source_thread_ids))
            connection.execute(query.values(eligible=0, updated_at=datetime.now(UTC).isoformat()))

    def execution_job_id(self, thread_id: int) -> str:
        with self.engine.begin() as connection:
            value = connection.execute(select(thread.c.execution_job_id).where(thread.c.id == thread_id)).scalar_one()
            if value:
                return str(value)
            value = (
                connection.execute(
                    select(task_job.c.job_id)
                    .join(task, task.c.id == task_job.c.task_id)
                    .join(job, job.c.id == task_job.c.job_id)
                    .where(task.c.thread_id == thread_id, job.c.state == JobState.COMPLETED.value)
                    .order_by(task.c.id, task_job.c.attempt)
                )
                .scalars()
                .first()
            )
            if value:
                connection.execute(
                    update(thread)
                    .where(thread.c.id == thread_id)
                    .values(execution_job_id=str(value), updated_at=datetime.now(UTC).isoformat())
                )
        return str(value) if value else ""

    def set_execution_job(self, thread_id: int, job_id: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(thread)
                .where(thread.c.id == thread_id)
                .values(execution_job_id=job_id, updated_at=datetime.now(UTC).isoformat())
            )

    def upsert_message(
        self,
        thread_id: int,
        source_message_id: str,
        actor: str,
        actor_type: MessageActorType,
        disposition: MessageDisposition,
        body: str,
        source_created_at: str,
    ) -> ThreadMessage:
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(thread_message).where(
                        thread_message.c.thread_id == thread_id,
                        thread_message.c.source_message_id == source_message_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                now = datetime.now(UTC).isoformat()
                connection.execute(
                    insert(thread_message).values(
                        thread_id=thread_id,
                        source_message_id=source_message_id,
                        actor=actor,
                        actor_type=actor_type.value,
                        disposition=disposition.value,
                        body=body,
                        source_created_at=source_created_at,
                        created_at=now,
                        updated_at=now,
                    )
                )
                row = (
                    connection.execute(
                        select(thread_message).where(
                            thread_message.c.thread_id == thread_id,
                            thread_message.c.source_message_id == source_message_id,
                        )
                    )
                    .mappings()
                    .one()
                )
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
                .order_by(thread_message.c.source_created_at, thread_message.c.source_message_id)
            ).mappings()
            return tuple(self._message(row) for row in rows)

    def accepted_messages(self, thread_id: int) -> tuple[ThreadMessage, ...]:
        return tuple(
            message for message in self.messages(thread_id) if message.disposition is MessageDisposition.ACCEPTED
        )

    def task_messages(self, task_id: int) -> tuple[ThreadMessage, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(thread_message)
                .join(task_message, task_message.c.message_id == thread_message.c.id)
                .where(task_message.c.task_id == task_id)
                .order_by(thread_message.c.source_created_at, thread_message.c.source_message_id)
            ).mappings()
            return tuple(self._message(row) for row in rows)

    def unassigned_messages(self, thread_id: int) -> tuple[ThreadMessage, ...]:
        with self.engine.connect() as connection:
            assigned = select(task_message.c.message_id)
            rows = connection.execute(
                select(thread_message)
                .where(
                    thread_message.c.thread_id == thread_id,
                    thread_message.c.disposition == MessageDisposition.ACCEPTED.value,
                    ~thread_message.c.id.in_(assigned),
                )
                .order_by(thread_message.c.source_created_at, thread_message.c.source_message_id)
            ).mappings()
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

    def create(
        self, thread_id: int, kind: TaskKind, messages: tuple[ThreadMessage, ...], predecessor_task_id: int
    ) -> Task:
        now = datetime.now(UTC).isoformat()
        with self.engine.begin() as connection:
            task_id = int(
                connection.execute(
                    insert(task)
                    .returning(task.c.id)
                    .values(
                        thread_id=thread_id,
                        kind=kind.value,
                        state=TaskState.UNRESOLVED.value,
                        predecessor_task_id=predecessor_task_id,
                        reason="",
                        created_at=now,
                        updated_at=now,
                    )
                ).scalar_one()
            )
            for message in messages:
                connection.execute(insert(task_message).values(task_id=task_id, message_id=message.id))
        return self.get(task_id)

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
            attempts = (
                connection.execute(
                    select(task_job.c.attempt).where(task_job.c.task_id == task_id).order_by(task_job.c.attempt.desc())
                )
                .scalars()
                .first()
            )
            connection.execute(insert(task_job).values(task_id=task_id, job_id=job_id, attempt=(attempts or 0) + 1))

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
    def _thread(row: RowMapping) -> Thread:
        return Thread(**{field: row[field] for field in Thread.model_fields})

    @staticmethod
    def _message(row: RowMapping) -> ThreadMessage:
        return ThreadMessage(**{field: row[field] for field in ThreadMessage.model_fields})

    @staticmethod
    def _task(row: RowMapping) -> Task:
        return Task(**{field: row[field] for field in Task.model_fields})
