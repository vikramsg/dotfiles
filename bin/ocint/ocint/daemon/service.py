import uuid
from datetime import UTC, datetime, timedelta
from shlex import join

from ocint.daemon.config import DaemonConfig
from ocint.daemon.models import (
    Channel,
    Claim,
    Continuation,
    Job,
    JobStage,
    JobState,
    OutboxItem,
    PromptObservation,
    RecoveryPlan,
    WorkRequest,
    WorkSource,
    WorkUpdate,
)
from ocint.daemon.repository import ControlRepository


def accept_work(request: WorkRequest, config: DaemonConfig, repository: ControlRepository) -> Job:
    configured = config.repository(request.repository)
    if configured.actors and request.actor not in configured.actors:
        raise PermissionError(f"actor is not allowed for {request.repository}: {request.actor}")
    parent_job_id = request.source_metadata.get("parent_job_id", "")
    continuation = continuation_for(repository.get(parent_job_id)) if parent_job_id else None
    return repository.submit(request, continuation=continuation)


def attach_command(job: Job) -> str:
    if not job.session_id or job.worktree_path is None or not job.server_url:
        return ""
    return join(["opencode", "attach", job.server_url, "--dir", str(job.worktree_path), "--session", job.session_id])


def build_follow_up(parent: Job, text: str, idempotency_key: str) -> WorkRequest:
    continuation_for(parent)
    return WorkRequest(
        idempotency_key=idempotency_key or uuid.uuid4().hex,
        conversation_id=parent.conversation_id,
        actor=parent.actor,
        repository=parent.repository,
        text=text,
        source=WorkSource.WEB,
        delivery_adapter="control",
        delivery_target=f"job:{parent.id}",
        source_metadata={"parent_job_id": parent.id},
    )


def continuation_for(parent: Job) -> Continuation:
    if parent.state is not JobState.COMPLETED:
        raise ValueError("follow-up parent must be completed")
    if parent.worktree_path is None or not parent.session_id:
        raise ValueError("follow-up parent workspace/session is no longer retained")
    return Continuation(
        parent_job_id=parent.id,
        workspace_owner_id=parent.workspace_owner_id,
        session_id=parent.session_id,
        worktree_path=parent.worktree_path,
        branch=parent.branch,
        base_revision=parent.commit_sha or parent.base_revision,
        server_url=parent.server_url,
    )


def cancel_job(repository: ControlRepository, job_id: str) -> Job:
    current = repository.get(job_id)
    if current.state is JobState.QUEUED:
        return repository.cancel_queued_with_outbox(
            current,
            terminal_update(current, JobState.CANCELLED, "cancelled"),
        )
    return repository.set_cancel(job_id)


def retry_job(repository: ControlRepository, job_id: str) -> Job:
    current = repository.get(job_id)
    if current.state not in {JobState.FAILED, JobState.CANCELLED}:
        raise ValueError("only failed or cancelled jobs can be retried")
    return repository.set_retry(job_id)


def recovery_plan(
    claim: Claim,
    session_status: str,
    prompt: PromptObservation,
    worktree_has_changes: bool,
    max_attempts: int,
) -> RecoveryPlan:
    error = "attempt recovered after runner lease loss"
    if (
        claim.job.stage is JobStage.EXECUTION
        and session_status == "idle"
        and (prompt.completed or worktree_has_changes)
    ):
        return RecoveryPlan(
            state=JobState.QUEUED,
            stage=JobStage.VALIDATION,
            reset_execution=False,
            error=error,
        )
    if claim.job.attempt_count >= max_attempts:
        return RecoveryPlan(
            state=JobState.FAILED,
            stage=claim.job.stage,
            reset_execution=False,
            error=error,
        )
    if claim.job.stage is not JobStage.EXECUTION:
        return RecoveryPlan(
            state=JobState.QUEUED,
            stage=claim.job.stage,
            reset_execution=False,
            error=error,
        )
    if session_status == "busy":
        return RecoveryPlan(
            state=JobState.QUEUED,
            stage=JobStage.EXECUTION,
            reset_execution=False,
            error=error,
        )
    return RecoveryPlan(
        state=JobState.QUEUED,
        stage=JobStage.EXECUTION,
        reset_execution=True,
        error=error,
    )


def terminal_update(job: Job, state: JobState, message: str) -> WorkUpdate:
    return WorkUpdate(
        conversation_id=job.conversation_id,
        job_id=job.id,
        status=state,
        message=message,
        session_id=job.session_id,
        artifact_url=job.pull_request_url,
    )


def matching_channel(item: OutboxItem, channels: list[Channel]) -> Channel:
    matches = [
        channel
        for channel in channels
        if channel.adapter_id == item.delivery_adapter and channel.accepts(item.delivery_target)
    ]
    if not matches:
        raise ValueError(f"no adapter {item.delivery_adapter} for target {item.delivery_target}")
    if len(matches) != 1:
        raise ValueError(f"ambiguous adapter {item.delivery_adapter} for target {item.delivery_target}")
    return matches[0]


def retirable_workspaces(repository: ControlRepository, retention_seconds: int) -> list[Job]:
    cutoff = datetime.now(UTC) - timedelta(seconds=retention_seconds)
    terminal = {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}
    eligible: list[Job] = []
    for owner in repository.workspace_owners_updated_before(cutoff):
        linked = repository.workspace_jobs(owner.workspace_owner_id)
        if linked and all(item.state in terminal and item.updated_at <= cutoff for item in linked):
            eligible.append(owner)
    return eligible
