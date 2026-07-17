import hashlib
from typing import Protocol

from ocint.daemon.config import DaemonConfig, RepositoryConfig
from ocint.daemon.github.models import (
    ActorType,
    CommentState,
    GitHubComment,
    GitHubIssue,
    GitHubPullRequest,
    StoredComment,
    StoredIssue,
)
from ocint.daemon.github.repository import GitHubRepository
from ocint.daemon.service import Job, WorkRequest


class WorkAcceptor(Protocol):
    def accept(self, request: WorkRequest) -> Job: ...
    def schedule_accepted(self, job_id: str) -> None: ...
    def resume(self, job_id: str, prompt: str) -> Job: ...


class GitHubTransport(Protocol):
    async def issues(self, repository: str, label: str) -> tuple[GitHubIssue, ...]: ...
    async def comments(self, repository: str, number: int) -> tuple[GitHubComment, ...]: ...
    async def pull_request(self, repository: str, number: int) -> GitHubPullRequest: ...
    async def find_pull_request(self, repository: str, branch: str, base: str) -> GitHubPullRequest | None: ...
    async def create_pull_request(
        self, repository: str, branch: str, base: str, title: str, body: str
    ) -> GitHubPullRequest: ...
    async def post_comment(self, repository: str, number: int, body: str) -> GitHubComment: ...


class GitHubService:
    def __init__(self, config: DaemonConfig, client: GitHubTransport, repository: GitHubRepository) -> None:
        self.config = config
        self.client = client
        self.repository = repository

    async def poll(self, acceptor: WorkAcceptor) -> None:
        for configured in self.config.repositories:
            for issue in await self.client.issues(configured.github_repository, self.config.github.issue_label):
                existing = self.repository.find_issue(configured.name, issue.id)
                if existing is None and not self._authorized(issue.user.login, configured):
                    continue
                comments = await self.client.comments(configured.github_repository, issue.number)
                stored = existing
                for comment in comments:
                    marker = self._marker_from_body(comment.body)
                    agent = self._is_agent_comment(comment, configured.github_repository, issue.number, comments)
                    state = (
                        CommentState.IGNORED
                        if agent
                        else (
                            CommentState.PENDING
                            if self._authorized(comment.user.login, configured)
                            else CommentState.REJECTED
                        )
                    )
                    if stored is None:
                        continue
                    self.repository.store_comment(
                        stored.id, comment, ActorType.AGENT if agent else ActorType.HUMAN, state, marker
                    )
                    if state is CommentState.REJECTED:
                        await self._respond(
                            stored, "unauthorized", comment.id, f"Actor @{comment.user.login} is not authorized."
                        )
                if stored is None:
                    initial_comments = tuple(
                        item
                        for item in comments
                        if self._authorized(item.user.login, configured)
                        and not self._is_agent_comment(item, configured.github_repository, issue.number, comments)
                    )
                    prompt = f"GitHub issue: {issue.title}\n\n{issue.body}" + "".join(
                        f"\n\nGitHub comment {item.id} by @{item.user.login}:\n{item.body}"
                        for item in sorted(initial_comments, key=lambda item: (item.created_at, item.id))
                    )
                    request = WorkRequest(
                        idempotency_key=f"github:{configured.github_repository}:{issue.id}",
                        actor=issue.user.login,
                        repository=configured.name,
                        prompt=prompt,
                    )
                    job = acceptor.accept(request)
                    stored = self.repository.issue(configured.name, configured.github_repository, issue, job.id)
                    for comment in comments:
                        marker = self._marker_from_body(comment.body)
                        agent = self._is_agent_comment(comment, configured.github_repository, issue.number, comments)
                        state = (
                            CommentState.IGNORED
                            if agent
                            else (
                                CommentState.PENDING
                                if self._authorized(comment.user.login, configured)
                                else CommentState.REJECTED
                            )
                        )
                        self.repository.store_comment(
                            stored.id, comment, ActorType.AGENT if agent else ActorType.HUMAN, state, marker
                        )
                        if state is CommentState.REJECTED:
                            await self._respond(
                                stored, "unauthorized", comment.id, f"Actor @{comment.user.login} is not authorized."
                            )
                    pending = self.repository.pending(stored.id)
                    if pending:
                        self.repository.activate(stored.id, pending)
                    acceptor.schedule_accepted(job.id)
                elif stored.active_anchor_comment_id == 0:
                    pending = self.repository.pending(stored.id)
                    if pending:
                        self.repository.activate(stored.id, pending)
                        if stored.pull_request_number:
                            pull = await self.client.pull_request(
                                configured.github_repository, stored.pull_request_number
                            )
                            if pull.state != "open" or pull.merged:
                                self.repository.set_error(stored.id, "owned pull request is closed or merged")
                                self.repository.finalize(stored.id, CommentState.ERRORED)
                                await self._respond(
                                    stored,
                                    "closed-pr",
                                    pending[-1].github_comment_id,
                                    "The owned pull request is closed or merged; no replacement will be created.",
                                )
                                continue
                        acceptor.resume(stored.job_id, self.followup_prompt(pending))
                    elif stored.initial_state == CommentState.PENDING.value:
                        acceptor.resume(stored.job_id, self.initial_prompt(stored.title, stored.body, ()))
                else:
                    active = self.repository.active(stored.id, stored.active_anchor_comment_id)
                    prompt = (
                        self.initial_prompt(stored.title, stored.body, active)
                        if stored.initial_state == CommentState.PENDING.value
                        else self.followup_prompt(active)
                    )
                    acceptor.resume(stored.job_id, prompt)

    async def publish(self, repository: str, branch: str, base: str, title: str, body: str) -> str:
        job_id = branch.removeprefix("ocint/")
        issue = self.repository.find_issue_for_job(job_id)
        if issue is None:
            pull = await self.client.find_pull_request(repository, branch, base)
            if pull is None:
                pull = await self.client.create_pull_request(repository, branch, base, title, body)
            return pull.html_url
        if (
            issue.pull_request_number
            and issue.initial_state == CommentState.ADDRESSED.value
            and not issue.active_anchor_comment_id
        ):
            return issue.pull_request_url
        if issue.pull_request_number:
            pull = await self.client.pull_request(repository, issue.pull_request_number)
            if pull.state != "open" or pull.merged:
                self.repository.set_error(issue.id, "owned pull request is closed or merged")
                self.repository.finalize(issue.id, CommentState.ERRORED)
                await self._respond(
                    issue,
                    "closed-pr",
                    issue.active_anchor_comment_id,
                    "The owned pull request is closed or merged; no replacement will be created.",
                )
                raise RuntimeError("owned pull request is closed or merged")
        else:
            pull = await self.client.find_pull_request(repository, branch, base)
            if pull is None:
                pull = await self.client.create_pull_request(repository, branch, base, issue.title, body)
            self.repository.set_pull_request(issue.id, pull.number, pull.html_url)
        await self._respond(
            issue,
            "addressed",
            issue.active_anchor_comment_id,
            f"Issue addressed: {pull.html_url}\n\nTo make further changes, add a comment.",
        )
        self.repository.finalize(issue.id, CommentState.ADDRESSED)
        return pull.html_url

    @staticmethod
    def initial_prompt(title: str, body: str, comments: tuple[StoredComment, ...]) -> str:
        additions = "".join(
            f"\n\nGitHub comment {item.github_comment_id} by @{item.actor_login}:\n{item.body}" for item in comments
        )
        return f"GitHub issue: {title}\n\n{body}{additions}"

    @staticmethod
    def followup_prompt(comments: tuple[StoredComment, ...]) -> str:
        return "GitHub follow-up comments:" + "".join(
            f"\n\nGitHub comment {item.github_comment_id} by @{item.actor_login}:\n{item.body}" for item in comments
        )

    @staticmethod
    def marker(repository: str, issue: int, outcome: str, anchor: int) -> str:
        digest = hashlib.sha256(f"{repository}:{issue}:{outcome}:{anchor}".encode()).hexdigest()[:24]
        return f"<!-- ocint:{digest} -->"

    async def _respond(self, issue: StoredIssue, outcome: str, anchor: int, text: str) -> None:
        marker = self.marker(issue.github_repository, issue.issue_number, outcome, anchor)
        comments = await self.client.comments(issue.github_repository, issue.issue_number)
        existing = next(
            (item for item in comments if item.user.login == self.config.github.agent_actor and marker in item.body),
            None,
        )
        response = existing or await self.client.post_comment(
            issue.github_repository, issue.issue_number, f"{text}\n\n{marker}"
        )
        self.repository.store_comment(issue.id, response, ActorType.AGENT, CommentState.IGNORED, marker)

    @staticmethod
    def _marker_from_body(body: str) -> str:
        start = body.find("<!-- ocint:")
        end = body.find(" -->", start)
        return body[start : end + 4] if start >= 0 and end >= 0 else ""

    def _is_agent_comment(
        self,
        comment: GitHubComment,
        repository: str,
        issue_number: int,
        comments: tuple[GitHubComment, ...],
    ) -> bool:
        if comment.user.login != self.config.github.agent_actor:
            return False
        marker = self._marker_from_body(comment.body)
        if not marker:
            return False
        anchors = (0, *(item.id for item in comments))
        return any(
            marker == self.marker(repository, issue_number, outcome, anchor)
            for outcome in ("addressed", "unauthorized", "closed-pr")
            for anchor in anchors
        )

    @staticmethod
    def _authorized(actor: str, repository: RepositoryConfig) -> bool:
        return not repository.actors or actor in repository.actors
