import builtins
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, and_, insert, select, update
from sqlalchemy.engine import RowMapping

from ocint.daemon.db.schema import job
from ocint.daemon.models import DirectOrigin, GitHubLogin, Job, JobStage, JobState, ThreadOrigin, WorkRequest
from ocint.daemon.service import (
    Checkpoint,
    CommitCheckpoint,
    PromptIntentCheckpoint,
    PromptSubmittedCheckpoint,
    PublicationRefusalCheckpoint,
    PullRequestCheckpoint,
    PushCheckpoint,
    SessionCheckpoint,
    StageCheckpoint,
    WorktreeCheckpoint,
)


class ControlRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def submit(self, request: WorkRequest) -> Job:
        now = datetime.now(UTC).isoformat()
        with self.engine.begin() as connection:
            existing = (
                connection.execute(select(job).where(job.c.idempotency_key == request.idempotency_key))
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                return self._job(existing)
            identifier = uuid.uuid4().hex
            connection.execute(
                insert(job).values(
                    id=identifier,
                    idempotency_key=request.idempotency_key,
                    actor=str(request.actor),
                    repository=request.repository,
                    prompt=request.prompt,
                    state=JobState.QUEUED.value,
                    stage=JobStage.EXECUTION.value,
                    session_id="",
                    server_url="",
                    worktree_path="",
                    branch="",
                    base_revision="",
                    prompt_intended=0,
                    prompt_submitted=0,
                    commit_sha="",
                    pushed=0,
                    pull_request_url="",
                    error="",
                    origin_kind=request.origin.kind,
                    origin_source_thread_id=(
                        request.origin.source_thread_id if isinstance(request.origin, ThreadOrigin) else ""
                    ),
                    origin_source_anchor_id=(
                        request.origin.source_anchor_id if isinstance(request.origin, ThreadOrigin) else ""
                    ),
                    publication_refusal="",
                    created_at=now,
                    updated_at=now,
                )
            )
        return self.get(identifier)

    def retry(self, previous: Job, request: WorkRequest) -> Job:
        now = datetime.now(UTC).isoformat()
        with self.engine.begin() as connection:
            existing = (
                connection.execute(select(job).where(job.c.idempotency_key == request.idempotency_key))
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                return self._job(existing)
            identifier = uuid.uuid4().hex
            connection.execute(
                insert(job).values(
                    id=identifier,
                    idempotency_key=request.idempotency_key,
                    actor=str(request.actor),
                    repository=request.repository,
                    prompt=request.prompt,
                    state=JobState.QUEUED.value,
                    stage=JobStage.EXECUTION.value,
                    session_id=previous.session_id,
                    server_url=previous.server_url,
                    worktree_path=str(previous.worktree_path or ""),
                    branch=previous.branch,
                    base_revision=previous.base_revision,
                    prompt_intended=0,
                    prompt_submitted=0,
                    commit_sha="",
                    pushed=0,
                    pull_request_url="",
                    error="",
                    origin_kind=request.origin.kind,
                    origin_source_thread_id=(
                        request.origin.source_thread_id if isinstance(request.origin, ThreadOrigin) else ""
                    ),
                    origin_source_anchor_id=(
                        request.origin.source_anchor_id if isinstance(request.origin, ThreadOrigin) else ""
                    ),
                    publication_refusal="",
                    created_at=now,
                    updated_at=now,
                )
            )
        return self.get(identifier)

    def claim(self, job_id: str) -> Job | None:
        now = datetime.now(UTC).isoformat()
        with self.engine.begin() as connection:
            result = connection.execute(
                update(job)
                .where(and_(job.c.id == job_id, job.c.state == JobState.QUEUED.value))
                .values(state=JobState.RUNNING.value, updated_at=now)
            )
        return self.get(job_id) if result.rowcount == 1 else None

    def pending_ids(self) -> builtins.list[str]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(job.c.id).where(job.c.state == JobState.QUEUED.value).order_by(job.c.created_at)
            ).scalars()
            return [str(identifier) for identifier in rows]

    def checkpoint(self, job_id: str, checkpoint: Checkpoint) -> Job:
        columns: dict[str, str | int] = {"updated_at": datetime.now(UTC).isoformat()}
        match checkpoint:
            case WorktreeCheckpoint(path=path, branch=branch, base_revision=base_revision):
                columns.update(worktree_path=str(path), branch=branch, base_revision=base_revision)
            case SessionCheckpoint(session_id=session_id, server_url=server_url):
                columns.update(session_id=session_id, server_url=server_url)
            case PromptIntentCheckpoint():
                columns["prompt_intended"] = 1
            case PromptSubmittedCheckpoint():
                columns["prompt_submitted"] = 1
            case StageCheckpoint(stage=stage):
                columns["stage"] = stage.value
            case CommitCheckpoint(sha=sha):
                columns.update(commit_sha=sha, stage=JobStage.PUSH.value)
            case PushCheckpoint(revision=revision):
                columns.update(pushed=1, stage=JobStage.PULL_REQUEST.value, base_revision=revision)
            case PullRequestCheckpoint(url=url):
                columns["pull_request_url"] = url
            case PublicationRefusalCheckpoint(reason=reason):
                columns["publication_refusal"] = reason
        with self.engine.begin() as connection:
            connection.execute(update(job).where(job.c.id == job_id).values(**columns))
        return self.get(job_id)

    def _finish(self, job_id: str, state: JobState, error: str = "") -> Job:
        values: dict[str, str] = {
            "state": state.value,
            "error": error,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        if state is JobState.COMPLETED:
            values["stage"] = JobStage.COMPLETE.value
        with self.engine.begin() as connection:
            connection.execute(update(job).where(job.c.id == job_id).values(**values))
        return self.get(job_id)

    def complete(self, job_id: str) -> Job:
        return self._finish(job_id, JobState.COMPLETED)

    def fail(self, job_id: str, error: str) -> Job:
        return self._finish(job_id, JobState.FAILED, error)

    def requeue(self, job_id: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(job)
                .where(and_(job.c.id == job_id, job.c.state == JobState.RUNNING.value))
                .values(state=JobState.QUEUED.value, updated_at=datetime.now(UTC).isoformat())
            )

    def reconcile(self) -> int:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(job)
                .where(job.c.state == JobState.RUNNING.value)
                .values(state=JobState.QUEUED.value, updated_at=datetime.now(UTC).isoformat())
            )
            return result.rowcount

    def get(self, job_id: str) -> Job:
        with self.engine.connect() as connection:
            row = connection.execute(select(job).where(job.c.id == job_id)).mappings().one()
        return self._job(row)

    def list(self, limit: int = 100) -> builtins.list[Job]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(job).order_by(job.c.created_at.desc()).limit(limit)).mappings().all()
        return [self._job(row) for row in rows]

    def _job(self, row: RowMapping) -> Job:
        path = str(row["worktree_path"])
        origin = (
            ThreadOrigin(
                source_thread_id=str(row["origin_source_thread_id"]),
                source_anchor_id=str(row["origin_source_anchor_id"]),
            )
            if str(row["origin_kind"]) == "thread"
            else DirectOrigin()
        )
        return Job(
            id=str(row["id"]),
            idempotency_key=str(row["idempotency_key"]),
            actor=GitHubLogin(str(row["actor"])),
            repository=str(row["repository"]),
            prompt=str(row["prompt"]),
            state=JobState(str(row["state"])),
            stage=JobStage(str(row["stage"])),
            session_id=str(row["session_id"]),
            server_url=str(row["server_url"]),
            worktree_path=Path(path) if path else None,
            branch=str(row["branch"]),
            base_revision=str(row["base_revision"]),
            prompt_intended=bool(row["prompt_intended"]),
            prompt_submitted=bool(row["prompt_submitted"]),
            commit_sha=str(row["commit_sha"]),
            pushed=bool(row["pushed"]),
            pull_request_url=str(row["pull_request_url"]),
            error=str(row["error"]),
            origin=origin,
            publication_refusal=str(row["publication_refusal"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
