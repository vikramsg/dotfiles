import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import pytest
from ocint.daemon.config import DaemonConfig, RepositoryConfig
from ocint.daemon.models import GitHubLogin, Job, JobStage, JobState, PublicationRequest, PublishedPublication
from ocint.daemon.service import (
    Checkpoint,
    CommitCheckpoint,
    JobExecutor,
    PromptDecision,
    PromptIntentCheckpoint,
    PromptObservation,
    PromptSubmittedCheckpoint,
    PullRequestCheckpoint,
    PushCheckpoint,
    SessionCheckpoint,
    StageCheckpoint,
    WorkRequest,
    Worktree,
    WorktreeCheckpoint,
    attach_command,
    prompt_action,
)


class GitFailure(StrEnum):
    NONE = "none"
    VALIDATION = "validation"


@dataclass
class StatefulJobStore:
    jobs: list[Job] = field(default_factory=list)
    reconciled: int = 0

    def submit(self, request: WorkRequest) -> Job:
        for job in self.jobs:
            if job.idempotency_key == request.idempotency_key:
                return job
        job = Job(
            id=f"job-{len(self.jobs) + 1}",
            idempotency_key=request.idempotency_key,
            actor=request.actor,
            repository=request.repository,
            title=request.title,
            prompt=request.prompt,
            state=JobState.QUEUED,
            stage=JobStage.EXECUTION,
            session_id="",
            server_url="",
            worktree_path=None,
            branch="",
            base_revision="",
            prompt_intended=False,
            prompt_submitted=False,
            commit_sha="",
            pushed=False,
            pull_request_url="",
            error="",
            created_at="now",
            updated_at="now",
        )
        self.jobs.append(job)
        return job

    def retry(self, previous: Job, request: WorkRequest) -> Job:
        job = self.submit(request).model_copy(
            update={
                "session_id": previous.session_id,
                "server_url": previous.server_url,
                "worktree_path": previous.worktree_path,
                "branch": previous.branch,
                "base_revision": previous.base_revision,
            }
        )
        self.save(job)
        return job

    def claim(self, job_id: str) -> Job | None:
        job = self.get(job_id)
        if job.state is not JobState.QUEUED:
            return None
        claimed = job.model_copy(update={"state": JobState.RUNNING})
        self.save(claimed)
        return claimed

    def pending_ids(self) -> list[str]:
        return [job.id for job in self.jobs if job.state is JobState.QUEUED]

    def get(self, job_id: str) -> Job:
        for job in self.jobs:
            if job.id == job_id:
                return job
        raise ValueError(f"job not found: {job_id}")

    def checkpoint(self, job_id: str, checkpoint: Checkpoint) -> Job:
        job = self.get(job_id)
        match checkpoint:
            case WorktreeCheckpoint(path=path, branch=branch, base_revision=base_revision):
                updated = job.model_copy(
                    update={"worktree_path": path, "branch": branch, "base_revision": base_revision}
                )
            case SessionCheckpoint(session_id=session_id, server_url=server_url):
                updated = job.model_copy(update={"session_id": session_id, "server_url": server_url})
            case PromptIntentCheckpoint():
                updated = job.model_copy(update={"prompt_intended": True})
            case PromptSubmittedCheckpoint():
                updated = job.model_copy(update={"prompt_submitted": True})
            case StageCheckpoint(stage=stage):
                updated = job.model_copy(update={"stage": stage})
            case CommitCheckpoint(sha=sha):
                updated = job.model_copy(update={"stage": JobStage.PUSH, "commit_sha": sha})
            case PushCheckpoint(revision=revision):
                updated = job.model_copy(
                    update={"stage": JobStage.PULL_REQUEST, "pushed": True, "base_revision": revision}
                )
            case PullRequestCheckpoint(url=url):
                updated = job.model_copy(update={"stage": JobStage.COMPLETE, "pull_request_url": url})
        self.save(updated)
        return updated

    def complete(self, job_id: str) -> Job:
        job = self.get(job_id).model_copy(update={"state": JobState.COMPLETED})
        self.save(job)
        return job

    def fail(self, job_id: str, error: str) -> Job:
        job = self.get(job_id).model_copy(update={"state": JobState.FAILED, "error": error})
        self.save(job)
        return job

    def requeue(self, job_id: str) -> None:
        self.save(self.get(job_id).model_copy(update={"state": JobState.QUEUED}))

    def reconcile(self) -> int:
        reconciled = 0
        for job in list(self.jobs):
            if job.state is JobState.RUNNING:
                self.requeue(job.id)
                reconciled += 1
        self.reconciled += reconciled
        return reconciled

    def save(self, updated: Job) -> None:
        for index, job in enumerate(self.jobs):
            if job.id == updated.id:
                self.jobs[index] = updated
                return
        raise ValueError(f"job not found: {updated.id}")


@dataclass
class StatefulOpenCode:
    server_url: str = "http://opencode.test"
    calls: list[str] = field(default_factory=list)
    wait_gate: asyncio.Event = field(default_factory=asyncio.Event)
    block_wait: bool = False
    observations: list[PromptObservation] = field(default_factory=list)

    async def create(self, directory: Path, identity: str) -> str:
        _ = directory
        self.calls.append("create")
        return f"session-{identity}"

    async def observe_prompt(self, directory: Path, session_id: str, text: str) -> PromptObservation:
        _ = (directory, session_id, text)
        self.calls.append("observe")
        if self.observations:
            return self.observations.pop(0)
        return PromptObservation(found=False, completed=False, active=False)

    async def prompt(self, directory: Path, session_id: str, text: str) -> None:
        _ = (directory, session_id, text)
        self.calls.append("prompt")

    async def wait_for_completion(self, directory: Path, session_id: str, text: str) -> None:
        _ = (directory, session_id, text)
        self.calls.append("wait")
        if self.block_wait:
            await self.wait_gate.wait()


@dataclass
class StatefulGit:
    root: Path
    failure: GitFailure = GitFailure.NONE
    calls: list[str] = field(default_factory=list)
    commit_messages: list[str] = field(default_factory=list)

    async def provision(self, repository: RepositoryConfig, job_id: str) -> Worktree:
        _ = repository
        self.calls.append("provision")
        path = self.root / job_id
        path.mkdir(parents=True, exist_ok=True)
        return Worktree(path=path, branch=f"ocint/{job_id}", base_revision="base")

    async def validate(self, worktree: Worktree, checks: tuple[tuple[str, ...], ...]) -> None:
        _ = (worktree, checks)
        self.calls.append("validate")
        if self.failure is GitFailure.VALIDATION:
            raise RuntimeError("validation failed")

    async def commit(self, worktree: Worktree, message: str, author_name: str, author_email: str) -> str:
        _ = (worktree, author_name, author_email)
        self.calls.append("commit")
        self.commit_messages.append(message)
        return "commit-sha"

    async def push(self, worktree: Worktree) -> None:
        _ = worktree
        self.calls.append("push")


@dataclass
class StatefulGitHub:
    calls: list[str] = field(default_factory=list)
    requests: list[PublicationRequest] = field(default_factory=list)

    async def publish(self, request: PublicationRequest) -> PublishedPublication:
        self.calls.append("pull_request")
        self.requests.append(request)
        return PublishedPublication(url="https://example.test/pull/1")


@dataclass
class CapacityGit(StatefulGit):
    gate: asyncio.Event = field(default_factory=asyncio.Event)
    started: asyncio.Event = field(default_factory=asyncio.Event)
    active: int = 0
    maximum_active: int = 0

    async def provision(self, repository: RepositoryConfig, job_id: str) -> Worktree:
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        if self.active == 2:
            self.started.set()
        await self.gate.wait()
        self.active -= 1
        return await super().provision(repository, job_id)


@pytest.fixture
def daemon_config(tmp_path: Path) -> DaemonConfig:
    return DaemonConfig.model_validate(
        {
            "database_path": tmp_path / "control.sqlite",
            "mirror_root": tmp_path / "mirrors",
            "worktree_root": tmp_path / "worktrees",
            "repositories": [
                {
                    "name": "repo",
                    "remote_url": "git@example.test:owner/repo.git",
                    "github_repository": "owner/repo",
                    "author_name": "Agent",
                    "author_email": "agent@example.test",
                    "actors": ["allowed"],
                }
            ],
            "scheduler": {"capacity": 2, "job_timeout_seconds": 1, "shutdown_timeout_seconds": 1},
            "opencode": {
                "config_file": tmp_path / "opencode-xdg" / "opencode" / "opencode.json",
                "xdg_config_home": tmp_path / "opencode-xdg",
                "xdg_data_home": tmp_path / "data",
            },
            "git": {
                "ssh_executable": tmp_path / "ssh",
                "identity_file": tmp_path / "identity",
                "known_hosts_file": tmp_path / "known_hosts",
            },
            "github": {"agent_actor": "maintainer"},
        }
    )


@pytest.fixture
def job_store() -> StatefulJobStore:
    return StatefulJobStore()


@pytest.mark.parametrize(
    ("observation", "expected"),
    [
        (PromptObservation(found=True, completed=True, active=False), PromptDecision.ADVANCE),
        (PromptObservation(found=True, completed=False, active=True), PromptDecision.WAIT),
        (PromptObservation(found=True, completed=False, active=False), PromptDecision.SUBMIT),
        (PromptObservation(found=False, completed=False, active=False), PromptDecision.SUBMIT),
        (PromptObservation(found=False, completed=False, active=True), PromptDecision.SUBMIT),
    ],
)
def test_prompt_decision_matrix(observation: PromptObservation, expected: PromptDecision) -> None:
    # GIVEN
    decision = prompt_action(observation)

    # THEN
    assert decision is expected


def test_attach_command_uses_runtime_path() -> None:
    # GIVEN
    job = Job(
        id="job",
        idempotency_key="key",
        actor=GitHubLogin("actor"),
        repository="repo",
        title="Work title",
        prompt="work",
        state=JobState.RUNNING,
        stage=JobStage.EXECUTION,
        session_id="session",
        server_url="http://localhost",
        worktree_path=Path("/tmp/work"),
        branch="ocint/job",
        base_revision="base",
        prompt_intended=True,
        prompt_submitted=True,
        commit_sha="",
        pushed=False,
        pull_request_url="",
        error="",
        created_at="now",
        updated_at="now",
    )

    # WHEN
    command = attach_command(job)

    # THEN
    assert command == "opencode attach http://localhost --dir /tmp/work --session session"


@pytest.mark.asyncio
async def test_executor_runs_every_stage_and_persists_result(
    tmp_path: Path, daemon_config: DaemonConfig, job_store: StatefulJobStore
) -> None:
    # GIVEN
    opencode = StatefulOpenCode()
    git = StatefulGit(tmp_path / "worktrees")
    github = StatefulGitHub()
    executor = JobExecutor(daemon_config, job_store, opencode, git, github)

    # WHEN
    job = executor.submit(
        WorkRequest(
            idempotency_key="full",
            actor=GitHubLogin("allowed"),
            repository="repo",
            title="Human-readable change",
            prompt="work",
        )
    )
    await executor.close()

    # THEN
    completed = job_store.get(job.id)
    assert git.calls == ["provision", "validate", "commit", "push"]
    assert opencode.calls == ["create", "observe", "prompt", "wait"]
    assert github.calls == ["pull_request"]
    assert git.commit_messages == ["ocint: Human-readable change"]
    assert [request.title for request in github.requests] == ["ocint: Human-readable change"]
    assert completed.state is JobState.COMPLETED
    assert completed.worktree_path == tmp_path / "worktrees" / job.id
    assert isinstance(completed.worktree_path, Path)
    assert completed.commit_sha == "commit-sha"
    assert completed.base_revision == "commit-sha"
    assert completed.pull_request_url == "https://example.test/pull/1"


@pytest.mark.asyncio
async def test_executor_marks_stage_failure_terminal(
    tmp_path: Path, daemon_config: DaemonConfig, job_store: StatefulJobStore
) -> None:
    # GIVEN
    executor = JobExecutor(
        daemon_config,
        job_store,
        StatefulOpenCode(),
        StatefulGit(tmp_path / "worktrees", GitFailure.VALIDATION),
        StatefulGitHub(),
    )

    # WHEN
    job = executor.submit(
        WorkRequest(
            idempotency_key="failure",
            actor=GitHubLogin("allowed"),
            repository="repo",
            title="Failure title",
            prompt="work",
        )
    )
    await executor.close()

    # THEN
    failed = job_store.get(job.id)
    assert failed.state is JobState.FAILED
    assert failed.error == "validation failed"


@pytest.mark.parametrize(
    ("stage", "expected_git", "expected_opencode", "expected_github"),
    [
        (JobStage.EXECUTION, ["validate", "commit", "push"], ["observe", "prompt", "wait"], ["pull_request"]),
        (JobStage.VALIDATION, ["validate", "commit", "push"], [], ["pull_request"]),
        (JobStage.COMMIT, ["commit", "push"], [], ["pull_request"]),
        (JobStage.PUSH, ["push"], [], ["pull_request"]),
        (JobStage.PULL_REQUEST, [], [], ["pull_request"]),
    ],
)
@pytest.mark.asyncio
async def test_start_resumes_only_unfinished_stage(
    tmp_path: Path,
    daemon_config: DaemonConfig,
    job_store: StatefulJobStore,
    stage: JobStage,
    expected_git: list[str],
    expected_opencode: list[str],
    expected_github: list[str],
) -> None:
    # GIVEN
    worktree = tmp_path / f"worktree-{stage.value}"
    worktree.mkdir()
    job = job_store.submit(
        WorkRequest(
            idempotency_key=stage.value,
            actor=GitHubLogin("allowed"),
            repository="repo",
            title="Resume title",
            prompt="work",
        )
    )
    job_store.checkpoint(job.id, WorktreeCheckpoint(path=worktree, branch=f"ocint/{job.id}", base_revision="base"))
    if stage is JobStage.EXECUTION:
        job_store.checkpoint(job.id, SessionCheckpoint(session_id="session", server_url="http://opencode.test"))
    else:
        job_store.checkpoint(job.id, StageCheckpoint(stage=stage))
    opencode = StatefulOpenCode()
    git = StatefulGit(tmp_path / "managed")
    github = StatefulGitHub()
    executor = JobExecutor(daemon_config, job_store, opencode, git, github)

    # WHEN
    await executor.start()
    await executor.close()

    # THEN
    assert git.calls == expected_git
    assert opencode.calls == expected_opencode
    assert github.calls == expected_github
    assert job_store.get(job.id).state is JobState.COMPLETED


@pytest.mark.asyncio
async def test_start_recovers_running_job(
    tmp_path: Path, daemon_config: DaemonConfig, job_store: StatefulJobStore
) -> None:
    # GIVEN
    job = job_store.submit(
        WorkRequest(
            idempotency_key="recovery",
            actor=GitHubLogin("allowed"),
            repository="repo",
            title="Recovery title",
            prompt="work",
        )
    )
    job_store.claim(job.id)
    executor = JobExecutor(
        daemon_config, job_store, StatefulOpenCode(), StatefulGit(tmp_path / "worktrees"), StatefulGitHub()
    )

    # WHEN
    await executor.start()
    await executor.close()

    # THEN
    assert job_store.reconciled == 1
    assert job_store.get(job.id).state is JobState.COMPLETED


@pytest.mark.parametrize(
    ("active", "expected_calls"),
    [
        (False, ["observe", "prompt", "wait"]),
        (True, ["observe", "wait"]),
    ],
)
@pytest.mark.asyncio
async def test_restart_recovers_interrupted_prompt_without_duplicating_active_prompt(
    tmp_path: Path,
    daemon_config: DaemonConfig,
    job_store: StatefulJobStore,
    active: bool,
    expected_calls: list[str],
) -> None:
    # GIVEN
    worktree = tmp_path / "interrupted-worktree"
    worktree.mkdir()
    job = job_store.submit(
        WorkRequest(
            idempotency_key="interrupted",
            actor=GitHubLogin("allowed"),
            repository="repo",
            title="Interrupted title",
            prompt="work",
        )
    )
    job_store.checkpoint(job.id, WorktreeCheckpoint(path=worktree, branch="ocint/interrupted", base_revision="base"))
    job_store.checkpoint(job.id, SessionCheckpoint(session_id="session", server_url="http://opencode.test"))
    job_store.checkpoint(job.id, PromptIntentCheckpoint())
    job_store.checkpoint(job.id, PromptSubmittedCheckpoint())
    job_store.claim(job.id)
    opencode = StatefulOpenCode(observations=[PromptObservation(found=True, completed=False, active=active)])
    executor = JobExecutor(
        daemon_config,
        job_store,
        opencode,
        StatefulGit(tmp_path / "managed"),
        StatefulGitHub(),
    )

    # WHEN
    await executor.start()
    await executor.close()

    # THEN
    assert opencode.calls == expected_calls
    assert opencode.calls.count("prompt") == (0 if active else 1)
    assert job_store.reconciled == 1
    assert job_store.get(job.id).state is JobState.COMPLETED


@pytest.mark.asyncio
async def test_duplicate_idempotent_submission_executes_once(
    tmp_path: Path, daemon_config: DaemonConfig, job_store: StatefulJobStore
) -> None:
    # GIVEN
    opencode = StatefulOpenCode(block_wait=True)
    git = StatefulGit(tmp_path / "worktrees")
    executor = JobExecutor(daemon_config, job_store, opencode, git, StatefulGitHub())
    request = WorkRequest(
        idempotency_key="duplicate",
        actor=GitHubLogin("allowed"),
        repository="repo",
        title="Duplicate title",
        prompt="work",
    )

    # WHEN
    first = executor.submit(request)
    second = executor.submit(request)
    while "wait" not in opencode.calls:
        await asyncio.sleep(0)

    # THEN
    assert first.id == second.id
    assert git.calls == ["provision"]
    assert opencode.calls == ["create", "observe", "prompt", "wait"]
    opencode.wait_gate.set()
    await executor.close()
    assert job_store.get(first.id).state is JobState.COMPLETED


@pytest.mark.asyncio
async def test_terminal_idempotent_submission_is_not_scheduled_again(
    tmp_path: Path, daemon_config: DaemonConfig, job_store: StatefulJobStore
) -> None:
    # GIVEN
    git = StatefulGit(tmp_path / "worktrees")
    executor = JobExecutor(daemon_config, job_store, StatefulOpenCode(), git, StatefulGitHub())
    request = WorkRequest(
        idempotency_key="terminal",
        actor=GitHubLogin("allowed"),
        repository="repo",
        title="Terminal title",
        prompt="work",
    )
    completed = executor.submit(request)
    await executor.wait_until_idle()

    # WHEN
    duplicate = executor.submit(request)
    await asyncio.sleep(0)

    # THEN
    assert duplicate.id == completed.id
    assert job_store.get(completed.id).state is JobState.COMPLETED
    assert executor.is_idle
    assert git.calls == ["provision", "validate", "commit", "push"]
    await executor.close()


@pytest.mark.asyncio
async def test_job_timeout_marks_job_failed(
    tmp_path: Path, daemon_config: DaemonConfig, job_store: StatefulJobStore
) -> None:
    # GIVEN
    daemon_config = daemon_config.model_copy(
        update={"scheduler": daemon_config.scheduler.model_copy(update={"shutdown_timeout_seconds": 3})}
    )
    executor = JobExecutor(
        daemon_config,
        job_store,
        StatefulOpenCode(block_wait=True),
        StatefulGit(tmp_path / "worktrees"),
        StatefulGitHub(),
    )

    # WHEN
    job = executor.submit(
        WorkRequest(
            idempotency_key="timeout",
            actor=GitHubLogin("allowed"),
            repository="repo",
            title="Timeout title",
            prompt="work",
        )
    )
    await executor.close()

    # THEN
    failed = job_store.get(job.id)
    assert failed.state is JobState.FAILED
    assert failed.error == "job timed out"


@pytest.mark.asyncio
async def test_executor_honors_capacity_without_polling(
    tmp_path: Path, daemon_config: DaemonConfig, job_store: StatefulJobStore
) -> None:
    # GIVEN
    git = CapacityGit(tmp_path / "worktrees")
    executor = JobExecutor(daemon_config, job_store, StatefulOpenCode(), git, StatefulGitHub())
    for number in range(3):
        executor.submit(
            WorkRequest(
                idempotency_key=f"capacity-{number}",
                actor=GitHubLogin("allowed"),
                repository="repo",
                title=f"Capacity title {number}",
                prompt="work",
            )
        )

    # WHEN
    await asyncio.wait_for(git.started.wait(), 2)

    # THEN
    assert git.maximum_active == 2
    assert len([job for job in job_store.jobs if job.state is JobState.QUEUED]) == 1
    git.gate.set()
    await executor.close()


def test_submission_enforces_actor_authorization(
    daemon_config: DaemonConfig, job_store: StatefulJobStore, tmp_path: Path
) -> None:
    # GIVEN
    executor = JobExecutor(daemon_config, job_store, StatefulOpenCode(), StatefulGit(tmp_path), StatefulGitHub())

    # WHEN / THEN
    with pytest.raises(PermissionError, match="not allowed"):
        executor.submit(
            WorkRequest(
                idempotency_key="denied",
                actor=GitHubLogin("denied"),
                repository="repo",
                title="Denied title",
                prompt="work",
            )
        )


@pytest.mark.asyncio
async def test_shutdown_timeout_requeues_active_job(
    tmp_path: Path, daemon_config: DaemonConfig, job_store: StatefulJobStore
) -> None:
    # GIVEN
    daemon_config = daemon_config.model_copy(
        update={"scheduler": daemon_config.scheduler.model_copy(update={"job_timeout_seconds": 10})}
    )
    opencode = StatefulOpenCode(block_wait=True)
    executor = JobExecutor(daemon_config, job_store, opencode, StatefulGit(tmp_path / "worktrees"), StatefulGitHub())
    job = executor.submit(
        WorkRequest(
            idempotency_key="shutdown",
            actor=GitHubLogin("allowed"),
            repository="repo",
            title="Shutdown title",
            prompt="work",
        )
    )
    while job_store.get(job.id).state is not JobState.RUNNING:
        await asyncio.sleep(0)

    # WHEN
    await executor.close()

    # THEN
    current = job_store.get(job.id)
    assert current.state is JobState.QUEUED
    assert current.stage is JobStage.EXECUTION
