import builtins
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, and_, insert, select, update
from sqlalchemy.engine import RowMapping

from ocint.daemon.db.schema import job, pull_request_ownership
from ocint.daemon.models import ActorIdentity, DirectOrigin, ThreadOrigin
from ocint.daemon.pull_request_job.models import (
    Checkpoint,
    CommitCheckpoint,
    PromptIntentCheckpoint,
    PromptSubmittedCheckpoint,
    PublicationRefusalCheckpoint,
    PullRequestCheckpoint,
    PullRequestJob,
    PullRequestJobRequest,
    PullRequestJobStage,
    PullRequestJobState,
    PushCheckpoint,
    SessionCheckpoint,
    StageCheckpoint,
    WorktreeCheckpoint,
)


class PullRequestJobRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def submit(self, request: PullRequestJobRequest) -> PullRequestJob:
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
                    title=request.title,
                    prompt=request.prompt,
                    state=PullRequestJobState.QUEUED.value,
                    stage=PullRequestJobStage.EXECUTION.value,
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

    def retry(self, previous: PullRequestJob, request: PullRequestJobRequest) -> PullRequestJob:
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
                    title=request.title,
                    prompt=request.prompt,
                    state=PullRequestJobState.QUEUED.value,
                    stage=PullRequestJobStage.EXECUTION.value,
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

    def claim(self, job_id: str) -> PullRequestJob | None:
        now = datetime.now(UTC).isoformat()
        with self.engine.begin() as connection:
            result = connection.execute(
                update(job)
                .where(and_(job.c.id == job_id, job.c.state == PullRequestJobState.QUEUED.value))
                .values(state=PullRequestJobState.RUNNING.value, updated_at=now)
            )
        return self.get(job_id) if result.rowcount == 1 else None

    def pending_ids(self) -> builtins.list[str]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(job.c.id).where(job.c.state == PullRequestJobState.QUEUED.value).order_by(job.c.created_at)
            ).scalars()
            return [str(identifier) for identifier in rows]

    def checkpoint(self, job_id: str, checkpoint: Checkpoint) -> PullRequestJob:
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
                columns.update(commit_sha=sha, stage=PullRequestJobStage.PUSH.value)
            case PushCheckpoint(revision=revision):
                columns.update(pushed=1, stage=PullRequestJobStage.PULL_REQUEST.value, base_revision=revision)
            case PullRequestCheckpoint(url=url):
                columns["pull_request_url"] = url
            case PublicationRefusalCheckpoint(reason=reason):
                columns["publication_refusal"] = reason
        with self.engine.begin() as connection:
            connection.execute(update(job).where(job.c.id == job_id).values(**columns))
        return self.get(job_id)

    def _finish(self, job_id: str, state: PullRequestJobState, error: str = "") -> PullRequestJob:
        values: dict[str, str] = {
            "state": state.value,
            "error": error,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        if state is PullRequestJobState.COMPLETED:
            values["stage"] = PullRequestJobStage.COMPLETE.value
        with self.engine.begin() as connection:
            connection.execute(update(job).where(job.c.id == job_id).values(**values))
        return self.get(job_id)

    def complete(self, job_id: str) -> PullRequestJob:
        return self._finish(job_id, PullRequestJobState.COMPLETED)

    def fail(self, job_id: str, error: str) -> PullRequestJob:
        return self._finish(job_id, PullRequestJobState.FAILED, error)

    def requeue(self, job_id: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(job)
                .where(and_(job.c.id == job_id, job.c.state == PullRequestJobState.RUNNING.value))
                .values(state=PullRequestJobState.QUEUED.value, updated_at=datetime.now(UTC).isoformat())
            )

    def reconcile(self) -> int:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(job)
                .where(job.c.state == PullRequestJobState.RUNNING.value)
                .values(state=PullRequestJobState.QUEUED.value, updated_at=datetime.now(UTC).isoformat())
            )
            return result.rowcount

    def get(self, job_id: str) -> PullRequestJob:
        with self.engine.connect() as connection:
            row = connection.execute(select(job).where(job.c.id == job_id)).mappings().one()
        return self._job(row)

    def list(self, limit: int = 100) -> builtins.list[PullRequestJob]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(job).order_by(job.c.created_at.desc()).limit(limit)).mappings().all()
        return [self._job(row) for row in rows]

    def owned_pull_request(self, source_thread_id: str, repository: str) -> tuple[int, str] | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(pull_request_ownership).where(
                        pull_request_ownership.c.source_thread_id == source_thread_id,
                        pull_request_ownership.c.repository == repository,
                    )
                )
                .mappings()
                .one_or_none()
            )
        return (int(row["number"]), str(row["url"])) if row is not None else None

    def set_owned_pull_request(self, source_thread_id: str, repository: str, number: int, url: str) -> None:
        with self.engine.begin() as connection:
            identity = (pull_request_ownership.c.source_thread_id == source_thread_id) & (
                pull_request_ownership.c.repository == repository
            )
            if connection.execute(select(pull_request_ownership.c.source_thread_id).where(identity)).first() is None:
                connection.execute(
                    insert(pull_request_ownership).values(
                        source_thread_id=source_thread_id, repository=repository, number=number, url=url
                    )
                )
            else:
                connection.execute(update(pull_request_ownership).where(identity).values(number=number, url=url))

    def _job(self, row: RowMapping) -> PullRequestJob:
        path = str(row["worktree_path"])
        origin = (
            ThreadOrigin(
                source_thread_id=str(row["origin_source_thread_id"]),
                source_anchor_id=str(row["origin_source_anchor_id"]),
            )
            if str(row["origin_kind"]) == "thread"
            else DirectOrigin()
        )
        return PullRequestJob(
            id=str(row["id"]),
            idempotency_key=str(row["idempotency_key"]),
            actor=ActorIdentity(str(row["actor"])),
            repository=str(row["repository"]),
            title=str(row["title"]),
            prompt=str(row["prompt"]),
            state=PullRequestJobState(str(row["state"])),
            stage=PullRequestJobStage(str(row["stage"])),
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
