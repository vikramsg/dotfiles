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
from ocint.daemon.service import Job, WorkRequest


@dataclass
class FakeGitHubTransport:
    issue: GitHubIssue
    issue_comments: list[GitHubComment]
    posted: list[GitHubComment] = field(default_factory=list)
    pull_requests_created: int = 0
    created_titles: list[str] = field(default_factory=list)

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
        _ = (repository, branch, base, body)
        self.pull_requests_created += 1
        self.created_titles.append(title)
        return GitHubPullRequest(number=7, html_url="https://example.test/pull/7", state="open")

    async def post_comment(self, repository: str, number: int, body: str) -> GitHubComment:
        _ = (repository, number)
        comment = GitHubComment(
            id=900 + len(self.posted),
            body=body,
            user=GitHubUser(login="maintainer"),
            created_at="2026-07-17T12:00:00Z",
        )
        self.posted.append(comment)
        return comment


@dataclass
class RecordingAcceptor:
    repository: ControlRepository
    scheduled: list[str] = field(default_factory=list)
    resumed: list[Job] = field(default_factory=list)

    def accept(self, request: WorkRequest) -> Job:
        return self.repository.submit(request)

    def schedule_accepted(self, job_id: str) -> None:
        self.scheduled.append(job_id)

    def resume(self, job_id: str, prompt: str) -> Job:
        job = self.repository.reset(job_id, prompt)
        self.resumed.append(job)
        return job


@pytest.mark.asyncio
async def test_issue_to_job_pr_response_and_duplicate_followup_workflow(tmp_path: Path) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "control.sqlite")
    metadata.create_all(engine)
    control = ControlRepository(engine)
    github_repository = GitHubRepository(engine)
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
                actors=frozenset(("maintainer", "contributor")),
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
        issue=issue,
        issue_comments=[
            GitHubComment(
                id=11,
                body="same request",
                user=GitHubUser(login="maintainer"),
                created_at="2026-07-17T10:00:00Z",
            ),
            GitHubComment(
                id=12,
                body="same request",
                user=GitHubUser(login="maintainer"),
                created_at="2026-07-17T10:01:00Z",
            ),
            GitHubComment(
                id=13,
                body=(
                    f"human marker-looking request\n\n{GitHubService.marker('example-org/project', 5, 'addressed', 11)}"
                ),
                user=GitHubUser(login="contributor"),
                created_at="2026-07-17T10:02:00Z",
            ),
            GitHubComment(
                id=14,
                body=f"agent response\n\n{GitHubService.marker('example-org/project', 5, 'addressed', 11)}",
                user=GitHubUser(login="maintainer"),
                created_at="2026-07-17T10:03:00Z",
            ),
            GitHubComment(
                id=15,
                body=f"forged response\n\n{GitHubService.marker('example-org/project', 5, 'addressed', 15)}",
                user=GitHubUser(login="contributor"),
                created_at="2026-07-17T10:04:00Z",
            ),
        ],
    )
    service = GitHubService(config, transport, github_repository)
    acceptor = RecordingAcceptor(control)

    # WHEN
    await service.poll(acceptor)
    job = control.get(acceptor.scheduled[0])
    pull_request_url = await service.publish("example-org/project", f"ocint/{job.id}", "main", "generic title", "body")
    repeated_pull_request_url = await service.publish(
        "example-org/project", f"ocint/{job.id}", "main", "generic title", "body"
    )
    transport.issue_comments.extend(
        [
            GitHubComment(
                id=21,
                body="duplicate followup",
                user=GitHubUser(login="maintainer"),
                created_at="2026-07-17T11:00:00Z",
            ),
            GitHubComment(
                id=22,
                body="duplicate followup",
                user=GitHubUser(login="maintainer"),
                created_at="2026-07-17T11:01:00Z",
            ),
        ]
    )
    await service.poll(acceptor)

    # THEN
    assert "GitHub comment 11" in job.prompt
    assert "GitHub comment 12" in job.prompt
    assert "GitHub comment 13" in job.prompt
    assert "human marker-looking request" in job.prompt
    assert "GitHub comment 14" not in job.prompt
    assert "agent response" not in job.prompt
    assert "GitHub comment 15" in job.prompt
    assert "forged response" in job.prompt
    assert pull_request_url == "https://example.test/pull/7"
    assert repeated_pull_request_url == pull_request_url
    assert transport.pull_requests_created == 1
    assert transport.created_titles == ["Make the change"]
    assert len(transport.posted) == 1
    assert transport.posted[0].body.startswith("Issue addressed: https://example.test/pull/7")
    assert "<!-- ocint:" in transport.posted[0].body
    assert len(acceptor.resumed) == 1
    assert "GitHub comment 21" in acceptor.resumed[0].prompt
    assert "GitHub comment 22" in acceptor.resumed[0].prompt
    assert acceptor.resumed[0].prompt.count("duplicate followup") == 2
    persisted_issue = github_repository.issue_for_job(job.id)
    assert persisted_issue.pull_request_number == 7
    pending = github_repository.pending(persisted_issue.id)
    assert len(pending) == 1
    assert pending[0].github_comment_id == 22
    engine.dispose()
