import builtins
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Connection, Engine, and_, insert, or_, select, update

from ocint.daemon.db.schema import attempt, job, lease, outbox, runner
from ocint.daemon.models import Claim, Job, JobStage, JobState, WorkUpdate
from ocint.daemon.repository import ControlRepository


class RunnerRepository:
    def __init__(self, engine: Engine, jobs: ControlRepository) -> None:
        self.engine = engine
        self.jobs = jobs

    def register(self, owner: str, lease_seconds: int) -> None:
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=lease_seconds)
        with self.engine.begin() as connection:
            existing = connection.scalar(select(runner.c.id).where(runner.c.id == owner))
            if existing:
                connection.execute(
                    update(runner)
                    .where(runner.c.id == owner)
                    .values(heartbeat_at=now.isoformat(), expires_at=expires.isoformat(), stopped_at="")
                )
            else:
                connection.execute(
                    insert(runner).values(
                        id=owner,
                        started_at=now.isoformat(),
                        heartbeat_at=now.isoformat(),
                        expires_at=expires.isoformat(),
                        stopped_at="",
                    )
                )

    def heartbeat(self, owner: str, lease_seconds: int) -> bool:
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            result = connection.execute(
                update(runner)
                .where(and_(runner.c.id == owner, runner.c.stopped_at == ""))
                .values(heartbeat_at=now.isoformat(), expires_at=(now + timedelta(seconds=lease_seconds)).isoformat())
            )
            return result.rowcount == 1

    def stop(self, owner: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(runner).where(runner.c.id == owner).values(stopped_at=datetime.now(UTC).isoformat())
            )

    def recoverable(self, owner: str) -> builtins.list[Claim]:
        now = datetime.now(UTC).isoformat()
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(
                        lease.c.id.label("lease_id"),
                        lease.c.attempt_id.label("attempt_id"),
                        lease.c.job_id.label("job_id"),
                    )
                    .outerjoin(runner, runner.c.id == lease.c.owner)
                    .where(
                        and_(
                            lease.c.released_at == "",
                            lease.c.owner != owner,
                            or_(
                                lease.c.expires_at <= now,
                                runner.c.id.is_(None),
                                runner.c.stopped_at != "",
                                runner.c.expires_at <= now,
                            ),
                        )
                    )
                )
                .mappings()
                .all()
            )
            return [
                Claim(
                    job=self.jobs.get(str(row["job_id"])),
                    attempt_id=str(row["attempt_id"]),
                    lease_id=str(row["lease_id"]),
                )
                for row in rows
            ]

    def recover(
        self,
        claim: Claim,
        state: JobState,
        stage: JobStage,
        error: str,
        *,
        reset_execution: bool,
        terminal_update: WorkUpdate | None = None,
    ) -> Job | None:
        now = datetime.now(UTC)
        connection = self.engine.connect()
        try:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            if not self._recoverable(connection, claim.lease_id, now):
                connection.rollback()
                return None
            connection.execute(update(lease).where(lease.c.id == claim.lease_id).values(released_at=now.isoformat()))
            connection.execute(
                update(attempt)
                .where(attempt.c.id == claim.attempt_id)
                .values(state=JobState.FAILED.value, error=error, finished_at=now.isoformat())
            )
            values = {
                "state": state.value,
                "stage": stage.value,
                "error": error,
                "updated_at": now.isoformat(),
            }
            if reset_execution:
                values.update({"session_id": "", "prompt_intended": 0, "prompt_submitted": 0})
            connection.execute(update(job).where(job.c.id == claim.job.id).values(**values))
            if terminal_update is not None:
                connection.execute(
                    insert(outbox).values(
                        id=uuid.uuid4().hex,
                        job_id=claim.job.id,
                        source=claim.job.source.value,
                        delivery_adapter=claim.job.delivery_adapter,
                        delivery_target=claim.job.delivery_target,
                        conversation_id=claim.job.conversation_id,
                        payload=terminal_update.model_dump_json(),
                        attempts=0,
                        available_at=now.isoformat(),
                        delivered_at="",
                        last_error="",
                        lease_id="",
                        lease_owner="",
                        lease_expires_at="",
                    )
                )
            connection.commit()
            return self.jobs.get(claim.job.id)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _recoverable(self, connection: Connection, lease_id: str, now: datetime) -> bool:
        row = (
            connection.execute(
                select(
                    lease.c.expires_at.label("lease_expires_at"),
                    lease.c.released_at,
                    runner.c.id.label("runner_id"),
                    runner.c.expires_at.label("runner_expires_at"),
                    runner.c.stopped_at,
                )
                .outerjoin(runner, runner.c.id == lease.c.owner)
                .where(lease.c.id == lease_id)
            )
            .mappings()
            .one_or_none()
        )
        if row is None or str(row["released_at"]):
            return False
        return (
            str(row["lease_expires_at"]) <= now.isoformat()
            or row["runner_id"] is None
            or bool(row["stopped_at"])
            or str(row["runner_expires_at"]) <= now.isoformat()
        )
