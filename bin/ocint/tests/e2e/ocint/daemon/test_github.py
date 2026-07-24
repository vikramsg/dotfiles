from dataclasses import dataclass, field
from itertools import chain
from pathlib import Path

import pytest
from alembic import command
from ocint.daemon.config import DaemonConfig, GitHubConfig, RepositoryConfig
from ocint.daemon.db import create_daemon_engine, migrate_daemon_db
from ocint.daemon.db.connection import alembic_config
from ocint.daemon.db.schema import metadata
from ocint.daemon.git import GitConfig
from ocint.daemon.github import GitHubRepositoryPolicy
from ocint.daemon.github.models import (
    GitHubComment,
    GitHubComments,
    GitHubIssue,
    GitHubIssues,
    GitHubPullRequest,
    GitHubRepositoryPolicies,
    GitHubUser,
)
from ocint.daemon.github.repository import GitHubRepository
from ocint.daemon.github.service import GitHubContext, GitHubService, marker
from ocint.daemon.models import GitHubLogin, PublicationRequest, RefusedPublication, ThreadOrigin
from ocint.daemon.opencode import OpenCodeConfig
from ocint.daemon.pull_request_job import (
    PullRequestJob,
    PullRequestJobRequest,
    PullRequestJobState,
)
from ocint.daemon.pull_request_job.models import (
    PublicationRefusalCheckpoint,
    PullRequestCheckpoint,
    SessionCheckpoint,
    WorktreeCheckpoint,
)
from ocint.daemon.pull_request_job.repository import PullRequestJobRepository
from ocint.daemon.tasks import TaskCoordinator, TaskState
from ocint.daemon.tasks.models import MessageClassification
from ocint.daemon.tasks.repository import TaskRepository
from sqlalchemy import text


@dataclass
class FakeGitHubTransport:
    issue: GitHubIssue
    issue_comments: list[GitHubComment]
    posted: list[GitHubComment] = field(default_factory=list)
    eligible: bool = True
    pull_state: str = "open"
    pull_merged: bool = False
    pull_requests_created: int = 0

    async def issues(self, repository: str, label: str) -> GitHubIssues:
        _ = (repository, label)
        return GitHubIssues(root=[self.issue] if self.eligible else [])

    async def comments(self, repository: str, number: int) -> GitHubComments:
        _ = (repository, number)
        return GitHubComments(root=list(chain(self.issue_comments, self.posted)))

    async def pull_request(self, repository: str, number: int) -> GitHubPullRequest:
        _ = (repository, number)
        return GitHubPullRequest(
            number=7,
            html_url="https://example.test/pull/7",
            state=self.pull_state,
            merged=self.pull_merged,
        )

    async def find_pull_request(self, repository: str, branch: str, base: str) -> GitHubPullRequest | None:
        _ = (repository, branch, base)
        return None

    async def create_pull_request(
        self, repository: str, branch: str, base: str, title: str, body: str
    ) -> GitHubPullRequest:
        _ = (repository, branch, base, title, body)
        self.pull_requests_created += 1
        return GitHubPullRequest(number=7, html_url="https://example.test/pull/7", state="open")

    async def post_comment(self, repository: str, number: int, body: str) -> GitHubComment:
        _ = (repository, number)
        response = GitHubComment(
            id=900 + len(self.posted),
            body=body,
            user=GitHubUser(login=GitHubLogin("maintainer")),
            created_at="2026-07-17T12:00:00Z",
        )
        self.posted.append(response)
        return response


@dataclass
class RecordingExecutor:
    repository: PullRequestJobRepository
    submitted: list[PullRequestJob] = field(default_factory=list)
    retried: list[PullRequestJob] = field(default_factory=list)
    scheduled: list[str] = field(default_factory=list)

    def accept(self, request: PullRequestJobRequest) -> PullRequestJob:
        return self.repository.submit(request)

    def accept_retry(self, previous: PullRequestJob, request: PullRequestJobRequest) -> PullRequestJob:
        return self.repository.retry(previous, request)

    def schedule_accepted(self, job_id: str) -> None:
        self.scheduled.append(job_id)

    def submit(self, request: PullRequestJobRequest) -> PullRequestJob:
        job = self.repository.submit(request)
        self.submitted.append(job)
        return job

    def retry(self, previous: PullRequestJob, request: PullRequestJobRequest) -> PullRequestJob:
        job = self.repository.retry(previous, request)
        self.retried.append(job)
        return job

    def get(self, job_id: str) -> PullRequestJob:
        return self.repository.get(job_id)

    def reusable(self, candidate_ids: tuple[str, ...]) -> PullRequestJob | None:
        candidates = (self.repository.get(job_id) for job_id in candidate_ids)
        return next((job for job in candidates if job.state is PullRequestJobState.COMPLETED), None)

    def abandon(self, job_id: str, reason: str) -> None:
        self.repository.fail(job_id, reason)


@pytest.mark.asyncio
async def test_closed_owned_pull_request_is_refused_and_task_transition_is_coordinator_owned(tmp_path: Path) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "control.sqlite")
    metadata.create_all(engine)
    control = PullRequestJobRepository(engine)
    tasks = TaskRepository(engine)
    transport = FakeGitHubTransport(
        GitHubIssue(
            id=100,
            number=5,
            title="Make the change",
            body="Issue body",
            created_at="2026-07-17T09:00:00Z",
            user=GitHubUser(login=GitHubLogin("maintainer")),
        ),
        [],
    )
    source = GitHubService(
        context=GitHubContext(
            config=GitHubConfig(agent_actor=GitHubLogin("automation-bot")),
            repositories=GitHubRepositoryPolicies(
                root=[
                    GitHubRepositoryPolicy(
                        name="dotfiles",
                        github_repository="example-org/project",
                        actors=frozenset((GitHubLogin("maintainer"),)),
                    )
                ]
            ),
            client=transport,
            repository=GitHubRepository(engine),
        )
    )
    executor = RecordingExecutor(control)
    coordinator = TaskCoordinator(source, tasks, executor)
    await coordinator.reconcile()
    job = executor.submitted[0]
    assert isinstance(job.origin, ThreadOrigin)
    publication = PublicationRequest(
        repository="example-org/project",
        branch="ocint/job",
        base="main",
        title="Make the change",
        body="Automated",
        origin=job.origin,
    )
    await source.publish(publication)
    transport.pull_state = "closed"

    # WHEN
    refusal = await source.publish(publication)
    assert isinstance(refusal, RefusedPublication)
    control.checkpoint(job.id, PublicationRefusalCheckpoint(reason=refusal.reason))
    control.fail(job.id, "owned pull request is closed or merged")
    await coordinator.reconcile()

    # THEN
    task = tasks.latest(tasks.threads()[0].id)
    assert task is not None
    assert task.state is TaskState.ERRORED
    assert transport.pull_requests_created == 1
    assert len(transport.posted) == 1
    assert "no replacement will be created" in transport.posted[0].body
    engine.dispose()


@pytest.mark.asyncio
async def test_failed_thread_task_with_new_comments_creates_successor_attempt(tmp_path: Path) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "control.sqlite")
    metadata.create_all(engine)
    control = PullRequestJobRepository(engine)
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
                actors=frozenset((GitHubLogin("maintainer"),)),
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
        github=GitHubConfig(agent_actor=GitHubLogin("maintainer")),
    )
    issue = GitHubIssue(
        id=100,
        number=5,
        title="Make the change",
        body="Issue body",
        created_at="2026-07-17T09:00:00Z",
        user=GitHubUser(login=GitHubLogin("maintainer")),
    )
    transport = FakeGitHubTransport(
        issue,
        [
            GitHubComment(
                id=10,
                body="not allowed",
                user=GitHubUser(login=GitHubLogin("mallory")),
                created_at="2026-07-17T09:59:00Z",
            ),
            GitHubComment(
                id=11,
                body="initial context",
                user=GitHubUser(login=GitHubLogin("maintainer")),
                created_at="2026-07-17T10:00:00Z",
            ),
            GitHubComment(
                id=14,
                body=(f"agent result\n\n{marker('example-org/project', 5, 'addressed', 'comment:11')}"),
                user=GitHubUser(login=GitHubLogin("maintainer")),
                created_at="2026-07-17T10:00:30Z",
            ),
        ],
    )
    repository_policies = GitHubRepositoryPolicies(
        root=[
            GitHubRepositoryPolicy(
                name="dotfiles",
                github_repository="example-org/project",
                actors=frozenset((GitHubLogin("maintainer"),)),
            ),
        ]
    )
    context = GitHubContext(
        config=config.github,
        repositories=repository_policies,
        client=transport,
        repository=GitHubRepository(engine),
    )
    source = GitHubService(context=context)
    executor = RecordingExecutor(control)
    coordinator = TaskCoordinator(source, tasks, executor)

    # WHEN
    await coordinator.reconcile()
    messages_after_first_poll = tasks.messages(tasks.threads()[0].id)
    await coordinator.reconcile()
    messages_after_second_poll = tasks.messages(tasks.threads()[0].id)
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
            user=GitHubUser(login=GitHubLogin("maintainer")),
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
            user=GitHubUser(login=GitHubLogin("maintainer")),
            created_at="2026-07-17T10:02:00Z",
        )
    )
    await coordinator.reconcile()
    follow_up = executor.retried[1]
    transport.eligible = False
    await coordinator.reconcile()
    ineligible = tasks.latest(tasks.threads()[0].id)
    transport.eligible = True
    await coordinator.reconcile()
    reactivated = tasks.latest(tasks.threads()[0].id)

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
    assert "agent result" not in successor.prompt
    assert any(item.body.startswith("Issue addressed: https://example.test/pull/7") for item in transport.posted)
    assert messages_after_second_poll == messages_after_first_poll
    assert thread.source_id == "github:example-org/project:100"
    assert messages_after_first_poll[0].source_id == "github:example-org/project:issue:100"
    assert messages_after_first_poll[0].source_created_at == "2026-07-17T09:00:00Z"
    assert messages_after_first_poll[2].source_id == "github:example-org/project:comment:11"
    assert [message.classification for message in messages_after_first_poll[:4]] == [
        MessageClassification.ACTIONABLE,
        MessageClassification.UNAUTHORIZED,
        MessageClassification.ACTIONABLE,
        MessageClassification.AGENT_RESPONSE,
    ]
    successor_task = tasks.task_for_job(successor.id)
    assert successor_task is not None
    assert len(tasks.task_messages(successor_task.id)) == 3
    assert ineligible is not None
    assert ineligible.state is TaskState.SKIPPED
    assert reactivated is not None
    assert reactivated.state is TaskState.UNRESOLVED
    assert reactivated.predecessor_task_id == ineligible.id
    assert "second follow-up" in executor.retried[-1].prompt
    addressed = tasks.get(successor_task.id)
    skipped = tasks.get(successor_task.predecessor_task_id)
    assert addressed.state is TaskState.ADDRESSED
    assert skipped.state is TaskState.SKIPPED
    assert "superseded" in skipped.reason
    engine.dispose()


@pytest.mark.asyncio
async def test_root_only_completion_response_does_not_schedule_follow_up(tmp_path: Path) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "control.sqlite")
    metadata.create_all(engine)
    control = PullRequestJobRepository(engine)
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
                actors=frozenset((GitHubLogin("maintainer"),)),
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
        github=GitHubConfig(agent_actor=GitHubLogin("maintainer")),
    )
    repository_policies = GitHubRepositoryPolicies(
        root=[
            GitHubRepositoryPolicy(
                name="dotfiles",
                github_repository="example-org/project",
                actors=frozenset((GitHubLogin("maintainer"),)),
            ),
        ]
    )
    transport = FakeGitHubTransport(
        GitHubIssue(
            id=100,
            number=5,
            title="Make the change",
            body="Issue body",
            created_at="2026-07-17T09:00:00Z",
            user=GitHubUser(login=GitHubLogin("maintainer")),
        ),
        [],
    )
    context = GitHubContext(
        config=config.github,
        repositories=repository_policies,
        client=transport,
        repository=GitHubRepository(engine),
    )
    source = GitHubService(context=context)
    executor = RecordingExecutor(control)
    coordinator = TaskCoordinator(source, tasks, executor)

    # WHEN
    await coordinator.reconcile()
    initial = executor.submitted[0]
    control.checkpoint(initial.id, PullRequestCheckpoint(url="https://example.test/pull/7"))
    control.complete(initial.id)
    await coordinator.reconcile()
    await coordinator.reconcile()

    # THEN
    thread = tasks.threads()[0]
    latest = tasks.latest(thread.id)
    assert latest is not None
    assert latest.state is TaskState.ADDRESSED
    assert len(executor.submitted) == 1
    assert executor.retried == []
    assert len(transport.posted) == 1
    response = next(
        message for message in tasks.messages(thread.id) if str(message.actor) == "maintainer" and message.id != 1
    )
    assert response.source_id == "github:example-org/project:comment:900"
    assert response.classification is MessageClassification.AGENT_RESPONSE
    engine.dispose()


@pytest.mark.asyncio
async def test_reset_task_identity_does_not_reuse_historical_job(tmp_path: Path) -> None:
    # GIVEN
    database = tmp_path / "control.sqlite"
    command.upgrade(alembic_config(database), "20260719_add_thread_execution_job")
    engine = create_daemon_engine(database)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO job VALUES ('historical', 'thread-task:1:attempt:1', 'maintainer', 'dotfiles', "
                "'historical', 'failed', 'execution', '', '', '', '', '', 0, 0, '', 0, '', "
                "'historical failure', 'now', 'now')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO thread VALUES (1, 'dotfiles', 'github', '100', 'maintainer', 1, '', 'Old', 'Old', 'now', 'now')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO thread_message VALUES "
                "(1, 1, '100', 'maintainer', 'human', 'accepted', 'old', 'now', 'now', 'now')"
            )
        )
        connection.execute(text("INSERT INTO task VALUES (1, 1, 'initial', 'unresolved', 0, '', 'now', 'now')"))
        connection.execute(text("INSERT INTO task_message VALUES (1, 1)"))
        connection.execute(
            text("INSERT INTO task_job VALUES (1, :job_id, 1)"),
            {"job_id": "historical"},
        )
    engine.dispose()
    migrate_daemon_db(database)
    engine = create_daemon_engine(database)
    control = PullRequestJobRepository(engine)
    tasks = TaskRepository(engine)
    config = DaemonConfig(
        database_path=database,
        mirror_root=tmp_path / "mirrors",
        worktree_root=tmp_path / "worktrees",
        repositories=(
            RepositoryConfig(
                name="dotfiles",
                remote_url="git@github.com:example-org/project.git",
                github_repository="example-org/project",
                author_name="ocint",
                author_email="ocint@example.invalid",
                actors=frozenset((GitHubLogin("maintainer"),)),
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
        github=GitHubConfig(agent_actor=GitHubLogin("maintainer")),
    )
    repository_policies = GitHubRepositoryPolicies(
        root=[
            GitHubRepositoryPolicy(
                name="dotfiles",
                github_repository="example-org/project",
                actors=frozenset((GitHubLogin("maintainer"),)),
            ),
        ]
    )
    transport = FakeGitHubTransport(
        GitHubIssue(
            id=100,
            number=5,
            title="Make the change",
            body="Issue body",
            created_at="2026-07-17T09:00:00Z",
            user=GitHubUser(login=GitHubLogin("maintainer")),
        ),
        [],
    )
    executor = RecordingExecutor(control)
    context = GitHubContext(
        config=config.github,
        repositories=repository_policies,
        client=transport,
        repository=GitHubRepository(engine),
    )
    source = GitHubService(context=context)
    coordinator = TaskCoordinator(source, tasks, executor)

    # WHEN
    await coordinator.reconcile()
    restarted_executor = RecordingExecutor(control)
    restarted = TaskCoordinator(source, tasks, restarted_executor)
    await restarted.reconcile()

    # THEN
    task = tasks.latest(tasks.threads()[0].id)
    assert task is not None
    assert task.id == 1
    assert len(executor.submitted) == 1
    submitted = executor.submitted[0]
    assert submitted.id != "historical"
    assert submitted.idempotency_key == ("thread-task:model-v2:source:github:example-org/project:100:task:1:attempt:1")
    assert tasks.latest_job_id(task.id) == submitted.id
    assert control.get("historical").error == "historical failure"
    assert control.get("historical").title == "ocint: complete job historical"
    assert restarted_executor.submitted == []
    assert restarted_executor.retried == []
    assert restarted_executor.scheduled == []
    assert tasks.latest_job_id(task.id) == submitted.id
    engine.dispose()
