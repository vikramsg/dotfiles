import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import pytest
from ocint.daemon.config import DaemonConfig, RepositoryConfig
from ocint.daemon.db import create_daemon_engine
from ocint.daemon.db.schema import metadata
from ocint.daemon.repository import ControlRepository
from ocint.daemon.service import (
    Job,
    JobExecutor,
    JobStage,
    JobState,
    PromptObservation,
    WorkRequest,
    Worktree,
    attach_command,
    prompt_action,
)


class GitFailure(StrEnum):
    NONE = "none"
    VALIDATION = "validation"


@dataclass
class StatefulOpenCode:
    server_url: str = "http://opencode.test"
    calls: list[str] = field(default_factory=list)
    wait_gate: asyncio.Event = field(default_factory=asyncio.Event)
    block_wait: bool = False

    async def create(self, directory: Path, identity: str) -> str:
        _ = directory
        self.calls.append("create")
        return f"session-{identity}"

    async def observe_prompt(self, directory: Path, session_id: str, text: str) -> PromptObservation:
        _ = (directory, session_id, text)
        self.calls.append("observe")
        return PromptObservation(found=False, completed=False)

    async def prompt(self, directory: Path, session_id: str, text: str) -> None:
        _ = (directory, session_id, text)
        self.calls.append("prompt")

    async def wait_idle(self, directory: Path, session_id: str) -> None:
        _ = (directory, session_id)
        self.calls.append("wait")
        if self.block_wait:
            await self.wait_gate.wait()


@dataclass
class StatefulGit:
    root: Path
    failure: GitFailure = GitFailure.NONE
    calls: list[str] = field(default_factory=list)

    async def provision(self, repository: RepositoryConfig, job_id: str) -> Worktree:
        _ = repository
        self.calls.append("provision")
        path = self.root / job_id
        path.mkdir(parents=True, exist_ok=True)
        return Worktree(path=path, branch=f"ocint/{job_id}", base_revision="base")

    async def validate(self, worktree: Worktree, checks: list[list[str]]) -> None:
        _ = (worktree, checks)
        self.calls.append("validate")
        if self.failure is GitFailure.VALIDATION:
            raise RuntimeError("validation failed")

    async def commit(self, worktree: Worktree, message: str, author_name: str, author_email: str) -> str:
        _ = (worktree, message, author_name, author_email)
        self.calls.append("commit")
        return "commit-sha"

    async def push(self, worktree: Worktree) -> None:
        _ = worktree
        self.calls.append("push")


@dataclass
class StatefulGitHub:
    calls: list[str] = field(default_factory=list)

    async def publish(self, repository: str, branch: str, base: str, title: str, body: str) -> str:
        _ = (repository, branch, base, title, body)
        self.calls.append("pull_request")
        return "https://example.test/pull/1"


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
        }
    )


@pytest.fixture
def repository(tmp_path: Path) -> ControlRepository:
    engine = create_daemon_engine(tmp_path / "service.sqlite")
    metadata.create_all(engine)
    return ControlRepository(engine)


def test_prompt_decision_and_attach_command() -> None:
    # GIVEN
    job = Job(
        id="job",
        idempotency_key="key",
        actor="actor",
        repository="repo",
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

    # WHEN / THEN
    assert prompt_action(PromptObservation(found=True, completed=False)) == "wait"
    assert prompt_action(PromptObservation(found=True, completed=True)) == "advance"
    assert attach_command(job) == "opencode attach http://localhost --dir /tmp/work --session session"


@pytest.mark.asyncio
async def test_executor_runs_every_stage_and_persists_result(
    tmp_path: Path, daemon_config: DaemonConfig, repository: ControlRepository
) -> None:
    # GIVEN
    opencode = StatefulOpenCode()
    git = StatefulGit(tmp_path / "worktrees")
    github = StatefulGitHub()
    executor = JobExecutor(daemon_config, repository, opencode, git, github)
    job = repository.submit(WorkRequest(idempotency_key="full", actor="allowed", repository="repo", prompt="work"))

    # WHEN
    await executor.execute(job.id)
    completed = repository.get(job.id)

    # THEN
    assert git.calls == ["provision", "validate", "commit", "push"]
    assert opencode.calls == ["create", "observe", "prompt", "wait"]
    assert github.calls == ["pull_request"]
    assert completed.state is JobState.COMPLETED
    assert completed.commit_sha == "commit-sha"
    assert completed.pull_request_url == "https://example.test/pull/1"


@pytest.mark.asyncio
async def test_executor_marks_stage_failure_terminal(
    tmp_path: Path, daemon_config: DaemonConfig, repository: ControlRepository
) -> None:
    # GIVEN
    executor = JobExecutor(
        daemon_config,
        repository,
        StatefulOpenCode(),
        StatefulGit(tmp_path / "worktrees", GitFailure.VALIDATION),
        StatefulGitHub(),
    )

    # WHEN
    job = executor.submit(WorkRequest(idempotency_key="failure", actor="allowed", repository="repo", prompt="work"))
    await executor.close()

    # THEN
    failed = repository.get(job.id)
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
async def test_restart_resumes_only_unfinished_stage(
    tmp_path: Path,
    daemon_config: DaemonConfig,
    repository: ControlRepository,
    stage: JobStage,
    expected_git: list[str],
    expected_opencode: list[str],
    expected_github: list[str],
) -> None:
    # GIVEN
    worktree = tmp_path / f"worktree-{stage.value}"
    worktree.mkdir()
    job = repository.submit(WorkRequest(idempotency_key=stage.value, actor="allowed", repository="repo", prompt="work"))
    values: dict[str, str | bool] = {
        "worktree_path": str(worktree),
        "branch": f"ocint/{job.id}",
        "base_revision": "base",
    }
    if stage is JobStage.EXECUTION:
        values.update({"session_id": "session", "server_url": "http://opencode.test"})
    repository.checkpoint(job.id, stage, **values)
    opencode = StatefulOpenCode()
    git = StatefulGit(tmp_path / "managed")
    github = StatefulGitHub()
    executor = JobExecutor(daemon_config, repository, opencode, git, github)

    # WHEN
    await executor.execute(job.id)

    # THEN
    assert git.calls == expected_git
    assert opencode.calls == expected_opencode
    assert github.calls == expected_github
    assert repository.get(job.id).state is JobState.COMPLETED


@pytest.mark.asyncio
async def test_executor_honors_capacity_without_polling(
    tmp_path: Path, daemon_config: DaemonConfig, repository: ControlRepository
) -> None:
    # GIVEN
    git = CapacityGit(tmp_path / "worktrees")
    executor = JobExecutor(daemon_config, repository, StatefulOpenCode(), git, StatefulGitHub())
    for number in range(3):
        executor.submit(
            WorkRequest(idempotency_key=f"capacity-{number}", actor="allowed", repository="repo", prompt="work")
        )

    # WHEN
    await asyncio.wait_for(git.started.wait(), 2)

    # THEN
    assert git.maximum_active == 2
    assert len([job for job in repository.list() if job.state is JobState.QUEUED]) == 1
    git.gate.set()
    await executor.close()


def test_submission_enforces_actor_authorization(
    daemon_config: DaemonConfig, repository: ControlRepository, tmp_path: Path
) -> None:
    # GIVEN
    executor = JobExecutor(daemon_config, repository, StatefulOpenCode(), StatefulGit(tmp_path), StatefulGitHub())

    # WHEN / THEN
    with pytest.raises(PermissionError, match="not allowed"):
        executor.submit(WorkRequest(idempotency_key="denied", actor="denied", repository="repo", prompt="work"))


@pytest.mark.asyncio
async def test_shutdown_timeout_requeues_active_job(
    tmp_path: Path, daemon_config: DaemonConfig, repository: ControlRepository
) -> None:
    # GIVEN
    daemon_config = daemon_config.model_copy(
        update={"scheduler": daemon_config.scheduler.model_copy(update={"job_timeout_seconds": 10})}
    )
    opencode = StatefulOpenCode(block_wait=True)
    executor = JobExecutor(daemon_config, repository, opencode, StatefulGit(tmp_path / "worktrees"), StatefulGitHub())
    job = executor.submit(WorkRequest(idempotency_key="shutdown", actor="allowed", repository="repo", prompt="work"))
    while repository.get(job.id).state is not JobState.RUNNING:
        await asyncio.sleep(0)

    # WHEN
    await executor.close()

    # THEN
    current = repository.get(job.id)
    assert current.state is JobState.QUEUED
    assert current.stage is JobStage.EXECUTION
