from __future__ import annotations

import builtins
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Connection, Engine, and_, exists, func, insert, or_, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError

from ocint.daemon.db.schema import artifact, attempt, event, job, lease, outbox, source_event, workspace
from ocint.daemon.models import (
    Artifact,
    Claim,
    Continuation,
    Job,
    JobStage,
    JobState,
    PersistedEvent,
    WorkRequest,
    WorkSource,
    Worktree,
    WorkUpdate,
)


class ControlRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def submit(self, request: WorkRequest, priority: int = 0, continuation: Continuation | None = None) -> Job:
        now = datetime.now(UTC)
        event_id = uuid.uuid4().hex
        job_id = uuid.uuid4().hex
        with self.engine.begin() as connection:
            existing = (
                connection.execute(select(job).where(job.c.idempotency_key == request.idempotency_key))
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                return self._job(existing)
            if continuation is not None:
                parent = (
                    connection.execute(
                        select(job)
                        .join(workspace, workspace.c.id == job.c.workspace_owner_id)
                        .where(
                            and_(
                                job.c.id == continuation.parent_job_id,
                                job.c.workspace_owner_id == continuation.workspace_owner_id,
                                job.c.worktree_path == str(continuation.worktree_path),
                                workspace.c.state == "active",
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if parent is None:
                    raise ValueError("continuation precondition changed before submission")
            try:
                connection.execute(
                    insert(source_event).values(
                        id=event_id,
                        idempotency_key=request.idempotency_key,
                        source=request.source.value,
                        payload=request.model_dump_json(),
                        created_at=now.isoformat(),
                    )
                )
                connection.execute(
                    insert(job).values(
                        id=job_id,
                        source_event_id=event_id,
                        idempotency_key=request.idempotency_key,
                        conversation_id=request.conversation_id,
                        actor=request.actor,
                        repository=request.repository,
                        prompt=request.text,
                        source=request.source.value,
                        delivery_adapter=request.delivery_adapter,
                        delivery_target=request.delivery_target,
                        parent_job_id=continuation.parent_job_id if continuation is not None else None,
                        workspace_owner_id=continuation.workspace_owner_id if continuation is not None else job_id,
                        state=JobState.QUEUED.value,
                        stage=JobStage.EXECUTION.value,
                        priority=priority,
                        attempt_count=0,
                        session_id=continuation.session_id if continuation is not None else "",
                        worktree_path=str(continuation.worktree_path) if continuation is not None else "",
                        branch=continuation.branch if continuation is not None else "",
                        base_revision=(continuation.base_revision if continuation is not None else ""),
                        prompt_intended=0,
                        prompt_submitted=0,
                        commit_sha="",
                        pushed=0,
                        pull_request_url="",
                        cancel_requested=0,
                        server_url=continuation.server_url if continuation is not None else "",
                        error="",
                        created_at=now.isoformat(),
                        updated_at=now.isoformat(),
                    )
                )
                if continuation is None:
                    connection.execute(
                        insert(workspace).values(
                            id=job_id,
                            worktree_path="",
                            state="active",
                            lease_id="",
                            lease_owner="",
                            lease_expires_at="",
                            attempts=0,
                            disposed=0,
                            removed=0,
                            last_error="",
                            updated_at=now.isoformat(),
                        )
                    )
                accepted = WorkUpdate(
                    conversation_id=request.conversation_id,
                    job_id=job_id,
                    status=JobState.QUEUED,
                    message=f"job {job_id} accepted",
                )
                connection.execute(
                    insert(outbox).values(
                        id=uuid.uuid4().hex,
                        job_id=job_id,
                        source=request.source.value,
                        delivery_adapter=request.delivery_adapter,
                        delivery_target=request.delivery_target,
                        conversation_id=request.conversation_id,
                        payload=accepted.model_dump_json(),
                        attempts=0,
                        available_at=now.isoformat(),
                        delivered_at="",
                        last_error="",
                        lease_id="",
                        lease_owner="",
                        lease_expires_at="",
                    )
                )
            except IntegrityError:
                existing = (
                    connection.execute(select(job).where(job.c.idempotency_key == request.idempotency_key))
                    .mappings()
                    .one()
                )
                return self._job(existing)
            created = connection.execute(select(job).where(job.c.id == job_id)).mappings().one()
            return self._job(created)

    def claim(self, owner: str, capacity: int, lease_seconds: int, config_snapshot: str) -> Claim | None:
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=lease_seconds)
        connection = self.engine.connect()
        try:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            active = connection.scalar(
                select(func.count())
                .select_from(lease)
                .where(and_(lease.c.released_at == "", lease.c.expires_at > now.isoformat()))
            )
            if active is None or active >= capacity:
                connection.rollback()
                return None
            active_job = job.alias("active_job")
            row = (
                connection.execute(
                    select(job)
                    .where(
                        and_(
                            job.c.state == JobState.QUEUED.value,
                            job.c.cancel_requested == 0,
                            or_(
                                job.c.worktree_path == "",
                                ~exists(
                                    select(lease.c.id)
                                    .join(
                                        active_job,
                                        active_job.c.id == lease.c.job_id,
                                    )
                                    .where(
                                        and_(
                                            active_job.c.worktree_path == job.c.worktree_path,
                                            lease.c.released_at == "",
                                            lease.c.expires_at > now.isoformat(),
                                        )
                                    )
                                ),
                            ),
                        )
                    )
                    .order_by(job.c.priority.desc(), job.c.created_at)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                connection.rollback()
                return None
            attempt_number = int(row["attempt_count"]) + 1
            attempt_id = uuid.uuid4().hex
            lease_id = uuid.uuid4().hex
            connection.execute(
                update(job)
                .where(and_(job.c.id == row["id"], job.c.state == JobState.QUEUED.value))
                .values(
                    state=JobState.PREPARING.value,
                    attempt_count=attempt_number,
                    updated_at=now.isoformat(),
                    error="",
                )
            )
            connection.execute(
                insert(attempt).values(
                    id=attempt_id,
                    job_id=row["id"],
                    number=attempt_number,
                    state=JobState.PREPARING.value,
                    config_snapshot=config_snapshot,
                    started_at=now.isoformat(),
                    finished_at="",
                    error="",
                )
            )
            connection.execute(
                insert(lease).values(
                    id=lease_id,
                    job_id=row["id"],
                    attempt_id=attempt_id,
                    owner=owner,
                    acquired_at=now.isoformat(),
                    heartbeat_at=now.isoformat(),
                    expires_at=expires.isoformat(),
                    released_at="",
                )
            )
            connection.commit()
            claimed = self.get(str(row["id"]))
            return Claim(job=claimed, attempt_id=attempt_id, lease_id=lease_id)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def heartbeat(self, lease_id: str, lease_seconds: int) -> bool:
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            result = connection.execute(
                update(lease)
                .where(and_(lease.c.id == lease_id, lease.c.released_at == "", lease.c.expires_at > now.isoformat()))
                .values(
                    heartbeat_at=now.isoformat(),
                    expires_at=(now + timedelta(seconds=lease_seconds)).isoformat(),
                )
            )
            return result.rowcount == 1

    def transition(
        self,
        job_id: str,
        attempt_id: str,
        lease_id: str,
        expected: JobState,
        state: JobState,
        error: str = "",
    ) -> Job:
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            self._assert_lease(connection, job_id, lease_id, now)
            result = connection.execute(
                update(job)
                .where(and_(job.c.id == job_id, job.c.state == expected.value))
                .values(state=state.value, error=error, updated_at=now.isoformat())
            )
            if result.rowcount != 1:
                raise ValueError(f"job {job_id} is not {expected.value}")
            connection.execute(update(attempt).where(attempt.c.id == attempt_id).values(state=state.value, error=error))
            connection.execute(
                insert(event).values(
                    job_id=job_id,
                    attempt_id=attempt_id,
                    kind="state",
                    payload=json.dumps({"state": state.value, "error": error}),
                    created_at=now.isoformat(),
                )
            )
        return self.get(job_id)

    def set_worktree(self, job_id: str, lease_id: str, worktree: Worktree) -> None:
        with self.engine.begin() as connection:
            self._assert_lease(connection, job_id, lease_id, datetime.now(UTC))
            connection.execute(
                update(job)
                .where(job.c.id == job_id)
                .values(
                    worktree_path=str(worktree.path),
                    branch=worktree.branch,
                    base_revision=worktree.base_revision,
                    updated_at=datetime.now(UTC).isoformat(),
                )
            )
            owner_id = connection.scalar(select(job.c.workspace_owner_id).where(job.c.id == job_id))
            connection.execute(
                update(workspace)
                .where(workspace.c.id == owner_id)
                .values(worktree_path=str(worktree.path), updated_at=datetime.now(UTC).isoformat())
            )

    def record_event(self, job_id: str, attempt_id: str, lease_id: str, kind: str, payload: str) -> None:
        with self.engine.begin() as connection:
            self._assert_lease(connection, job_id, lease_id, datetime.now(UTC))
            connection.execute(
                insert(event).values(
                    job_id=job_id,
                    attempt_id=attempt_id,
                    kind=kind,
                    payload=payload,
                    created_at=datetime.now(UTC).isoformat(),
                )
            )

    def set_session(self, job_id: str, lease_id: str, session_id: str, server_url: str) -> None:
        with self.engine.begin() as connection:
            self._assert_lease(connection, job_id, lease_id, datetime.now(UTC))
            connection.execute(
                update(job)
                .where(job.c.id == job_id)
                .values(session_id=session_id, server_url=server_url, updated_at=datetime.now(UTC).isoformat())
            )

    def reset_execution(self, job_id: str, lease_id: str) -> None:
        with self.engine.begin() as connection:
            self._assert_lease(connection, job_id, lease_id, datetime.now(UTC))
            connection.execute(
                update(job)
                .where(job.c.id == job_id)
                .values(
                    session_id="",
                    prompt_intended=0,
                    prompt_submitted=0,
                    updated_at=datetime.now(UTC).isoformat(),
                )
            )

    def finish(self, job_id: str, attempt_id: str, lease_id: str, state: JobState, error: str = "") -> Job:
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            self._assert_lease(connection, job_id, lease_id, now)
            connection.execute(
                update(job).where(job.c.id == job_id).values(state=state.value, error=error, updated_at=now.isoformat())
            )
            connection.execute(
                update(attempt)
                .where(attempt.c.id == attempt_id)
                .values(state=state.value, error=error, finished_at=now.isoformat())
            )
            connection.execute(update(lease).where(lease.c.id == lease_id).values(released_at=now.isoformat()))
            connection.execute(
                insert(event).values(
                    job_id=job_id,
                    attempt_id=attempt_id,
                    kind="state",
                    payload=json.dumps({"state": state.value, "error": error}),
                    created_at=now.isoformat(),
                )
            )
        return self.get(job_id)

    def requeue(self, job_id: str, attempt_id: str, lease_id: str, error: str) -> Job:
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            self._assert_lease(connection, job_id, lease_id, now)
            connection.execute(
                update(job)
                .where(job.c.id == job_id)
                .values(state=JobState.QUEUED.value, error=error, updated_at=now.isoformat())
            )
            connection.execute(
                update(attempt)
                .where(attempt.c.id == attempt_id)
                .values(state=JobState.FAILED.value, error=error, finished_at=now.isoformat())
            )
            connection.execute(update(lease).where(lease.c.id == lease_id).values(released_at=now.isoformat()))
        return self.get(job_id)

    def add_artifact(self, job_id: str, lease_id: str, item: Artifact) -> Artifact:
        with self.engine.begin() as connection:
            self._assert_lease(connection, job_id, lease_id, datetime.now(UTC))
            existing = (
                connection.execute(
                    select(artifact).where(and_(artifact.c.job_id == job_id, artifact.c.kind == item.kind))
                )
                .mappings()
                .one_or_none()
            )
            if existing is None:
                connection.execute(
                    insert(artifact).values(
                        id=uuid.uuid4().hex,
                        job_id=job_id,
                        kind=item.kind,
                        value=item.value,
                        url=item.url,
                        created_at=datetime.now(UTC).isoformat(),
                    )
                )
                return item
            return Artifact(kind=str(existing["kind"]), value=str(existing["value"]), url=str(existing["url"]))

    def checkpoint(
        self,
        job_id: str,
        lease_id: str,
        stage: JobStage,
        *,
        prompt_intended: bool | None = None,
        prompt_submitted: bool | None = None,
        commit_sha: str | None = None,
        pushed: bool | None = None,
        pull_request_url: str | None = None,
    ) -> Job:
        now = datetime.now(UTC)
        values = {"stage": stage.value, "updated_at": now.isoformat()}
        if prompt_intended is not None:
            values["prompt_intended"] = int(prompt_intended)
        if prompt_submitted is not None:
            values["prompt_submitted"] = int(prompt_submitted)
        if commit_sha is not None:
            values["commit_sha"] = commit_sha
        if pushed is not None:
            values["pushed"] = int(pushed)
        if pull_request_url is not None:
            values["pull_request_url"] = pull_request_url
        with self.engine.begin() as connection:
            self._assert_lease(connection, job_id, lease_id, now)
            connection.execute(update(job).where(job.c.id == job_id).values(**values))
        return self.get(job_id)

    def set_cancel(self, job_id: str) -> Job:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(job)
                .where(job.c.id == job_id)
                .values(cancel_requested=1, updated_at=datetime.now(UTC).isoformat())
            )
            if result.rowcount != 1:
                raise ValueError(f"job not found: {job_id}")
        return self.get(job_id)

    def cancel_queued_with_outbox(self, current: Job, update_item: WorkUpdate) -> Job:
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            result = connection.execute(
                update(job)
                .where(and_(job.c.id == current.id, job.c.state == JobState.QUEUED.value))
                .values(
                    state=JobState.CANCELLED.value,
                    cancel_requested=1,
                    error="cancelled",
                    updated_at=now.isoformat(),
                )
            )
            if result.rowcount != 1:
                raise ValueError("queued job changed before cancellation")
            connection.execute(
                insert(outbox).values(
                    id=uuid.uuid4().hex,
                    job_id=current.id,
                    source=current.source.value,
                    delivery_adapter=current.delivery_adapter,
                    delivery_target=current.delivery_target,
                    conversation_id=current.conversation_id,
                    payload=update_item.model_dump_json(),
                    attempts=0,
                    available_at=now.isoformat(),
                    delivered_at="",
                    last_error="",
                    lease_id="",
                    lease_owner="",
                    lease_expires_at="",
                )
            )
        return self.get(current.id)

    def set_retry(self, job_id: str) -> Job:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(job)
                .where(job.c.id == job_id)
                .values(
                    state=JobState.QUEUED.value,
                    cancel_requested=0,
                    error="",
                    updated_at=datetime.now(UTC).isoformat(),
                )
            )
            if result.rowcount != 1:
                raise ValueError(f"job not found: {job_id}")
        return self.get(job_id)

    def finish_with_outbox(
        self,
        claim: Claim,
        state: JobState,
        error: str,
        update_item: WorkUpdate,
    ) -> Job:
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            self._assert_lease(connection, claim.job.id, claim.lease_id, now)
            connection.execute(
                update(job)
                .where(job.c.id == claim.job.id)
                .values(
                    state=state.value,
                    stage=JobStage.COMPLETE.value if state is JobState.COMPLETED else claim.job.stage.value,
                    error=error,
                    updated_at=now.isoformat(),
                )
            )
            connection.execute(
                update(attempt)
                .where(attempt.c.id == claim.attempt_id)
                .values(state=state.value, finished_at=now.isoformat(), error=error)
            )
            connection.execute(update(lease).where(lease.c.id == claim.lease_id).values(released_at=now.isoformat()))
            connection.execute(
                insert(outbox).values(
                    id=uuid.uuid4().hex,
                    job_id=claim.job.id,
                    source=claim.job.source.value,
                    delivery_adapter=claim.job.delivery_adapter,
                    delivery_target=claim.job.delivery_target,
                    conversation_id=claim.job.conversation_id,
                    payload=update_item.model_dump_json(),
                    attempts=0,
                    available_at=now.isoformat(),
                    delivered_at="",
                    last_error="",
                    lease_id="",
                    lease_owner="",
                    lease_expires_at="",
                )
            )
        return self.get(claim.job.id)

    def events(self, job_id: str, after: int = 0) -> builtins.list[PersistedEvent]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(event).where(and_(event.c.job_id == job_id, event.c.id > after)).order_by(event.c.id)
                )
                .mappings()
                .all()
            )
            return [
                PersistedEvent(
                    id=int(row["id"]),
                    kind=str(row["kind"]),
                    payload=str(row["payload"]),
                    created_at=datetime.fromisoformat(str(row["created_at"])),
                )
                for row in rows
            ]

    def record_control_event(self, job_id: str, kind: str, payload: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                insert(event).values(
                    job_id=job_id,
                    attempt_id=None,
                    kind=kind,
                    payload=payload,
                    created_at=datetime.now(UTC).isoformat(),
                )
            )

    def origin(self, job_id: str) -> WorkRequest:
        with self.engine.connect() as connection:
            payload = connection.scalar(
                select(source_event.c.payload)
                .join(job, job.c.source_event_id == source_event.c.id)
                .where(job.c.id == job_id)
            )
            if not isinstance(payload, str):
                raise ValueError(f"job not found: {job_id}")
            return WorkRequest.model_validate_json(payload)

    def artifacts(self, job_id: str) -> builtins.list[Artifact]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(artifact).where(artifact.c.job_id == job_id)).mappings().all()
            return [Artifact(kind=str(row["kind"]), value=str(row["value"]), url=str(row["url"])) for row in rows]

    def workspace_owners_updated_before(self, cutoff: datetime) -> builtins.list[Job]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(job).where(
                        and_(
                            job.c.id == job.c.workspace_owner_id,
                            job.c.worktree_path != "",
                            job.c.updated_at <= cutoff.isoformat(),
                        )
                    )
                )
                .mappings()
                .all()
            )
            return [self._job(row) for row in rows]

    def workspace_jobs(self, workspace_owner_id: str) -> builtins.list[Job]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(job).where(job.c.workspace_owner_id == workspace_owner_id).order_by(job.c.created_at)
                )
                .mappings()
                .all()
            )
            return [self._job(row) for row in rows]

    def get(self, job_id: str) -> Job:
        with self.engine.connect() as connection:
            return self._get(connection, job_id)

    def list(self, limit: int = 100) -> builtins.list[Job]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(job).order_by(job.c.created_at.desc()).limit(limit)).mappings().all()
            return [self._job(row) for row in rows]

    def _get(self, connection: Connection, job_id: str) -> Job:
        row = connection.execute(select(job).where(job.c.id == job_id)).mappings().one()
        return self._job(row)

    def _assert_lease(self, connection: Connection, job_id: str, lease_id: str, now: datetime) -> None:
        active = connection.scalar(
            select(func.count())
            .select_from(lease)
            .where(
                and_(
                    lease.c.id == lease_id,
                    lease.c.job_id == job_id,
                    lease.c.released_at == "",
                    lease.c.expires_at > now.isoformat(),
                )
            )
        )
        if active != 1:
            raise RuntimeError(f"lease lost for job {job_id}")

    def _job(self, row: RowMapping) -> Job:
        path = str(row["worktree_path"])
        return Job(
            id=str(row["id"]),
            idempotency_key=str(row["idempotency_key"]),
            conversation_id=str(row["conversation_id"]),
            actor=str(row["actor"]),
            repository=str(row["repository"]),
            prompt=str(row["prompt"]),
            source=WorkSource(str(row["source"])),
            delivery_adapter=str(row["delivery_adapter"]),
            delivery_target=str(row["delivery_target"]),
            parent_job_id=str(row["parent_job_id"] or ""),
            workspace_owner_id=str(row["workspace_owner_id"]),
            state=JobState(str(row["state"])),
            stage=JobStage(str(row["stage"])),
            priority=int(row["priority"]),
            attempt_count=int(row["attempt_count"]),
            session_id=str(row["session_id"]),
            worktree_path=Path(path) if path else None,
            branch=str(row["branch"]),
            base_revision=str(row["base_revision"]),
            prompt_intended=bool(row["prompt_intended"]),
            prompt_submitted=bool(row["prompt_submitted"]),
            commit_sha=str(row["commit_sha"]),
            pushed=bool(row["pushed"]),
            pull_request_url=str(row["pull_request_url"]),
            cancel_requested=bool(row["cancel_requested"]),
            server_url=str(row["server_url"]),
            error=str(row["error"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )
