from dataclasses import dataclass, field
from pathlib import Path

import pytest
from ocint.daemon.db import create_daemon_engine
from ocint.daemon.db.schema import metadata
from ocint.daemon.models import (
    GitHubLogin,
    GitRepository,
    PromptObservation,
    PublicationRequest,
    PublicationResult,
    PublishedPublication,
    RefusedPublication,
    Worktree,
)
from ocint.daemon.pull_request_job.config import PullRequestJobConfig, RepositoryPolicy, SchedulerPolicy
from ocint.daemon.pull_request_job.repository import PullRequestJobRepository
from ocint.daemon.pull_request_job.run import PullRequestJobRunner
from ocint.daemon.slack.config import SlackChannelConfig, SlackConfig
from ocint.daemon.slack.models import SlackAuth, SlackHistory, SlackMessage, SlackMessages, SlackPostedMessage
from ocint.daemon.slack.repository import SlackRepository
from ocint.daemon.slack.service import SlackContext, SlackService
from ocint.daemon.tasks.models import TaskState
from ocint.daemon.tasks.repository import TaskRepository
from ocint.daemon.tasks.run import TaskCoordinator


@dataclass
class E2ESlackTransport:
    roots: list[SlackMessage]
    thread_messages: list[SlackMessage]
    posted: list[str] = field(default_factory=list)
    reactions: list[str] = field(default_factory=list)

    async def auth_test(self) -> SlackAuth:
        return SlackAuth(user_id="UBOT", bot_id="BBOT", team_id="T1")

    async def history(self, channel: str, oldest: str = "", cursor: str = "") -> SlackHistory:
        del channel, oldest, cursor
        return SlackHistory(messages=SlackMessages(root=self.roots))

    async def replies(self, channel: str, root_ts: str, cursor: str = "") -> SlackHistory:
        del channel, root_ts, cursor
        return SlackHistory(messages=SlackMessages(root=self.thread_messages))

    async def post_message(self, channel: str, thread_ts: str, text: str, client_msg_id: str) -> SlackPostedMessage:
        del channel, thread_ts
        timestamp = f"1000000009.{len(self.posted) + 1:06d}"
        self.posted.append(text)
        self.thread_messages.append(
            SlackMessage(ts=timestamp, text=text, user="UBOT", bot_id="BBOT", client_msg_id=client_msg_id)
        )
        return SlackPostedMessage(ts=timestamp)

    async def add_reaction(self, channel: str, timestamp: str, name: str) -> None:
        del channel, timestamp
        if name not in self.reactions:
            self.reactions.append(name)


@dataclass
class FakeOpenCode:
    server_url: str = "http://127.0.0.1:4097"
    prompts: list[str] = field(default_factory=list)

    async def create(self, directory: Path, identity: str) -> str:
        del directory, identity
        return "session"

    async def observe_prompt(self, directory: Path, session_id: str, text: str) -> PromptObservation:
        del directory, session_id, text
        return PromptObservation(found=False, completed=False, active=False)

    async def prompt(self, directory: Path, session_id: str, text: str) -> None:
        del directory, session_id
        self.prompts.append(text)

    async def wait_for_completion(self, directory: Path, session_id: str, text: str) -> None:
        del directory, session_id, text


@dataclass
class FakeGit:
    root: Path

    async def provision(self, repository: GitRepository, job_id: str) -> Worktree:
        del repository
        return Worktree(path=self.root / job_id, branch=f"ocint/{job_id}", base_revision="base")

    async def validate(self, worktree: Worktree, checks: tuple[tuple[str, ...], ...]) -> None:
        del worktree, checks

    async def commit(self, worktree: Worktree, message: str, author_name: str, author_email: str) -> str:
        del worktree, message, author_name, author_email
        return "commit"

    async def push(self, worktree: Worktree) -> None:
        del worktree


@dataclass
class FakeGitHubPublisher:
    closed: bool = False
    requests: list[PublicationRequest] = field(default_factory=list)

    async def publish(self, request: PublicationRequest) -> PublicationResult:
        self.requests.append(request)
        if request.owned_pull_request_number and self.closed:
            return RefusedPublication()
        return PublishedPublication(url="https://example.test/pull/7", number=7)


@pytest.mark.asyncio
async def test_slack_task_lifecycle_completion_restart_reopen_follow_up_and_closed_pr(tmp_path: Path) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "control.sqlite")
    metadata.create_all(engine)
    root = SlackMessage(ts="1000000000.000001", text="Change config\nPreserve behavior", user="U1")
    transport = E2ESlackTransport(roots=[root], thread_messages=[root])
    source = SlackService(
        context=SlackContext(
            config=SlackConfig(
                workspace_id="T1",
                channels=(
                    SlackChannelConfig(
                        channel_id="C1",
                        repository="dotfiles",
                        authorized_users=frozenset(("U1",)),
                        initial_oldest=root.ts,
                    ),
                ),
            ),
            auth=SlackAuth(user_id="UBOT", bot_id="BBOT", team_id="T1"),
            client=transport,
            repository=SlackRepository(engine),
        )
    )
    control = PullRequestJobRepository(engine)
    tasks = TaskRepository(engine)
    publisher = FakeGitHubPublisher()
    runner = PullRequestJobRunner(
        PullRequestJobConfig(
            repositories=(
                RepositoryPolicy(
                    git_repository=GitRepository(name="dotfiles", remote_url="git@example.test:dotfiles.git"),
                    github_repository="owner/dotfiles",
                    author_name="Agent",
                    author_email="agent@example.test",
                    actors=frozenset((GitHubLogin("maintainer"),)),
                    checks=(),
                ),
            ),
            scheduler=SchedulerPolicy(capacity=1, job_timeout_seconds=30, shutdown_timeout_seconds=5),
        ),
        control,
        FakeOpenCode(),
        FakeGit(tmp_path / "worktrees"),
        publisher,
    )
    coordinator = TaskCoordinator(source, tasks, runner)
    await coordinator.reconcile()
    await runner.wait_until_idle()
    await coordinator.reconcile()
    ownership = control.owned_pull_request("slack:T1:C1:1000000000.000001", "owner/dotfiles")
    assert ownership == (7, "https://example.test/pull/7")

    # WHEN a restarted coordinator sees an authorized canonical reopen and follow-up
    reopened = SlackMessage(
        ts="1000000001.000001",
        text="reopen <https://workspace.slack.com/archives/C1/p1000000000000001>",
        user="U1",
    )
    follow_up = SlackMessage(ts="1000000001.000002", thread_ts=reopened.ts, text="Also update docs", user="U1")
    transport.roots = [reopened]
    transport.thread_messages = [reopened, follow_up]
    publisher.closed = True
    restarted = TaskCoordinator(source, tasks, runner)
    await restarted.reconcile()
    await runner.wait_until_idle()
    await restarted.reconcile()

    # THEN
    final_task = tasks.latest(tasks.threads()[0].id)
    assert final_task is not None
    assert final_task.state is TaskState.ERRORED
    final_job = control.get(tasks.latest_job_id(final_task.id))
    assert len(control.list()) == 2
    assert "Also update docs" in final_job.prompt
    assert publisher.requests[-1].owned_pull_request_number == 7
    assert transport.posted == [
        "Issue addressed: https://example.test/pull/7\n\nTo make further changes, add a comment.",
        "The owned pull request is closed or merged; no replacement will be created.",
    ]
    assert transport.reactions == ["white_check_mark"]
    assert source.context.repository.open_threads("C1") == ()
    await runner.close()
    engine.dispose()
