from dataclasses import dataclass, field
from itertools import chain
from pathlib import Path

import pytest
from ocint.daemon.config import DaemonConfig, GitConfig, GitHubConfig, OpenCodeConfig, RepositoryConfig
from ocint.daemon.db import create_daemon_engine
from ocint.daemon.db.schema import metadata
from ocint.daemon.github.models import GitHubComment, GitHubIssue, GitHubPullRequest, GitHubUser
from ocint.daemon.github.repository import GitHubRepository
from ocint.daemon.github.service import GitHubService
from ocint.daemon.repository import ControlRepository
from ocint.daemon.service import Job, PullRequestCheckpoint, SessionCheckpoint, WorkRequest, WorktreeCheckpoint
from ocint.daemon.tasks import TaskCoordinator, TaskState
from ocint.daemon.tasks.repository import TaskRepository


@dataclass
class FakeGitHubTransport:
    issue: GitHubIssue
    issue_comments: list[GitHubComment]
    posted: list[GitHubComment] = field(default_factory=list)

    async def issues(self, repository: str, label: str) -> tuple[GitHubIssue, ...]:
        _ = (repository, label)
        return (self.issue,)

    async def comments(self, repository: str, number: int) -> tuple[GitHubComment, ...]:
        _ = (repository, number)
        return tuple(chain(self.issue_comments, self.posted))

    async def pull_request(self, repository: str, number: int) -> GitHubPullRequest:
        _ = (repository, number)
        return GitHubPullRequest(number=7, html_url="https://example.test/pull/7", state="open")

    async def find_pull_request(self, repository: str, branch: str, base: str) -> GitHubPullRequest | None:
        _ = (repository, branch, base)
        return None

    async def create_pull_request(
        self, repository: str, branch: str, base: str, title: str, body: str
    ) -> GitHubPullRequest:
        _ = (repository, branch, base, title, body)
        return GitHubPullRequest(number=7, html_url="https://example.test/pull/7", state="open")

    async def post_comment(self, repository: str, number: int, body: str) -> GitHubComment:
        _ = (repository, number)
        response = GitHubComment(
            id=900 + len(self.posted),
            body=body,
            user=GitHubUser(login="maintainer"),
            created_at="2026-07-17T12:00:00Z",
        )
        self.posted.append(response)
        return response


@dataclass
class RecordingExecutor:
    repository: ControlRepository
    submitted: list[Job] = field(default_factory=list)
    retried: list[Job] = field(default_factory=list)

    def submit(self, request: WorkRequest) -> Job:
        job = self.repository.submit(request)
        self.submitted.append(job)
        return job

    def retry(self, previous: Job, request: WorkRequest) -> Job:
        job = self.repository.retry(previous, request)
        self.retried.append(job)
        return job

    def get(self, job_id: str) -> Job:
        return self.repository.get(job_id)

    def abandon(self, job_id: str, reason: str) -> None:
        self.repository.fail(job_id, reason)


@pytest.mark.asyncio
async def test_failed_thread_task_with_new_comments_creates_successor_attempt(tmp_path: Path) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "control.sqlite")
    metadata.create_all(engine)
    control = ControlRepository(engine)
    tasks = TaskRepository(engine)
    config = DaemonConfig(
        database_path=tmp_path / "control.sqlite",
        mirror_root=tmp_path / "mirrors",
        worktree_root=tmp_path / "worktrees",
        repositories=(
            RepositoryConfig(
                name="dotfiles",
                remote_url="git@github.com:example-org/project.git",
                github_repository="example-org/project",
                author_name="ocint",
                author_email="ocint@example.invalid",
                actors=frozenset(("maintainer",)),
            ),
        ),
        opencode=OpenCodeConfig(
            config_file=tmp_path / "opencode-xdg" / "opencode" / "opencode.json",
            xdg_config_home=tmp_path / "opencode-xdg",
            xdg_data_home=tmp_path / "data",
        ),
        git=GitConfig(
            ssh_executable=tmp_path / "ssh",
            identity_file=tmp_path / "identity",
            known_hosts_file=tmp_path / "known_hosts",
        ),
        github=GitHubConfig(agent_actor="maintainer"),
    )
    issue = GitHubIssue(
        id=100,
        number=5,
        title="Make the change",
        body="Issue body",
        user=GitHubUser(login="maintainer"),
    )
    transport = FakeGitHubTransport(
        issue,
        [
            GitHubComment(
                id=11,
                body="initial context",
                user=GitHubUser(login="maintainer"),
                created_at="2026-07-17T10:00:00Z",
            )
        ],
    )
    source = GitHubService(config, transport, GitHubRepository(engine), tasks)
    executor = RecordingExecutor(control)
    coordinator = TaskCoordinator(source, tasks, executor)

    # WHEN
    await coordinator.reconcile()
    initial = executor.submitted[0]
    control.checkpoint(
        initial.id, WorktreeCheckpoint(path=tmp_path / "worktree", branch="ocint/original", base_revision="base")
    )
    control.checkpoint(initial.id, SessionCheckpoint(session_id="session", server_url="http://opencode.test"))
    control.fail(initial.id, "stream failed")
    transport.issue_comments.append(
        GitHubComment(
            id=12,
            body="new direction",
            user=GitHubUser(login="maintainer"),
            created_at="2026-07-17T10:01:00Z",
        )
    )
    await coordinator.reconcile()
    successor = executor.retried[0]
    control.checkpoint(successor.id, PullRequestCheckpoint(url="https://example.test/pull/7"))
    control.complete(successor.id)
    await coordinator.reconcile()
    transport.issue_comments.append(
        GitHubComment(
            id=13,
            body="second follow-up",
            user=GitHubUser(login="maintainer"),
            created_at="2026-07-17T10:02:00Z",
        )
    )
    await coordinator.reconcile()
    follow_up = executor.retried[1]

    # THEN
    thread = tasks.threads()[0]
    latest = tasks.latest(thread.id)
    assert latest is not None
    assert latest.state is TaskState.UNRESOLVED
    assert latest.predecessor_task_id > 0
    assert successor.worktree_path == tmp_path / "worktree"
    assert successor.session_id == "session"
    assert successor.branch == "ocint/original"
    assert follow_up.worktree_path == successor.worktree_path
    assert follow_up.session_id == successor.session_id
    assert follow_up.branch == successor.branch
    assert "initial context" in successor.prompt
    assert "new direction" in successor.prompt
    assert transport.posted[0].body.startswith("Issue addressed: https://example.test/pull/7")
    addressed = tasks.get(latest.predecessor_task_id)
    skipped = tasks.get(addressed.predecessor_task_id)
    assert addressed.state is TaskState.ADDRESSED
    assert skipped.state is TaskState.SKIPPED
    assert "superseded" in skipped.reason
    engine.dispose()
