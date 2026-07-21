import hashlib
from typing import Protocol

from ocint.daemon.config import DaemonConfig, RepositoryConfig
from ocint.daemon.github.models import GitHubComment, GitHubIssue, GitHubPullRequest, StoredIssue
from ocint.daemon.github.repository import GitHubRepository
from ocint.daemon.logging import get_logger
from ocint.daemon.service import Job
from ocint.daemon.tasks.models import MessageClassification, Task, TaskState
from ocint.daemon.tasks.repository import TaskRepository

logger = get_logger("github")


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
    def __init__(
        self, config: DaemonConfig, client: GitHubTransport, repository: GitHubRepository, tasks: TaskRepository
    ) -> None:
        self.config = config
        self.client = client
        self.repository = repository
        self.tasks = tasks

    async def poll(self) -> None:
        for configured in self.config.repositories:
            issues = await self.client.issues(configured.github_repository, self.config.github.issue_label)
            eligible: list[int] = []
            logger.info(
                "repository issues polled",
                repository=configured.github_repository,
                label=self.config.github.issue_label,
                issues=len(issues),
            )
            for issue in issues:
                authorized = self._authorized(issue.user.login, configured)
                if not authorized:
                    logger.warning(
                        "issue rejected",
                        repository=configured.github_repository,
                        issue=issue.number,
                        actor=issue.user.login,
                    )
                else:
                    eligible.append(issue.id)
                thread = self.tasks.upsert_thread(
                    f"github:{configured.github_repository}:{issue.id}",
                    issue.title,
                )
                root = self.tasks.upsert_message(
                    thread.id,
                    f"github:{configured.github_repository}:issue:{issue.id}",
                    issue.user.login,
                    MessageClassification.ACTIONABLE if authorized else MessageClassification.UNAUTHORIZED,
                    issue.body,
                    issue.created_at,
                )
                stored = self.repository.upsert_issue(
                    thread.id,
                    root.id,
                    configured.name,
                    configured.github_repository,
                    issue.id,
                    issue.number,
                    authorized,
                )
                comments = await self.client.comments(configured.github_repository, issue.number)
                for comment in comments:
                    marker = self._marker_from_body(comment.body)
                    agent = self._is_agent_comment(comment, stored, comments)
                    classification = (
                        MessageClassification.AGENT_RESPONSE
                        if agent
                        else (
                            MessageClassification.ACTIONABLE
                            if self._authorized(comment.user.login, configured)
                            else MessageClassification.UNAUTHORIZED
                        )
                    )
                    message = self.tasks.upsert_message(
                        thread.id,
                        f"github:{configured.github_repository}:comment:{comment.id}",
                        comment.user.login,
                        classification,
                        comment.body,
                        comment.created_at,
                    )
                    self.repository.upsert_comment(comment.id, message.id, marker)
                    if classification is MessageClassification.UNAUTHORIZED:
                        logger.warning(
                            "thread message rejected",
                            repository=configured.github_repository,
                            issue=issue.number,
                            message=comment.id,
                            actor=comment.user.login,
                        )
                        await self._respond(
                            stored,
                            "unauthorized",
                            self.repository.comment_anchor(comment.id),
                            f"Actor @{comment.user.login} is not authorized.",
                        )
            self.repository.synchronize(configured.name, tuple(eligible))

    def eligible(self, thread_id: int) -> bool:
        issue = self.repository.issue_for_thread(thread_id)
        return issue is not None and issue.eligible

    def configured_repository(self, thread_id: int) -> str:
        issue = self.repository.issue_for_thread(thread_id)
        if issue is None:
            raise RuntimeError(f"GitHub mapping missing for thread {thread_id}")
        return issue.configured_repository

    async def publish(self, repository: str, branch: str, base: str, title: str, body: str, job_id: str) -> str:
        task = self.tasks.task_for_job(job_id)
        if task is None:
            pull = await self.client.find_pull_request(repository, branch, base)
            if pull is None:
                pull = await self.client.create_pull_request(repository, branch, base, title, body)
                logger.info("pull request created", repository=repository, branch=branch, pull_request=pull.html_url)
            else:
                logger.info("pull request reused", repository=repository, branch=branch, pull_request=pull.html_url)
            return pull.html_url
        issue = self.repository.issue_for_thread(task.thread_id)
        if issue is None:
            raise RuntimeError(f"GitHub mapping missing for task {task.id}")
        if issue.pull_request_number:
            pull = await self.client.pull_request(repository, issue.pull_request_number)
            if pull.state != "open" or pull.merged:
                self.tasks.set_state(task.id, TaskState.ERRORED, "owned pull request is closed or merged")
                await self._respond(
                    issue,
                    "closed-pr",
                    self._task_anchor(issue, task),
                    "The owned pull request is closed or merged; no replacement will be created.",
                )
                raise RuntimeError("owned pull request is closed or merged")
            return pull.html_url
        thread = self.tasks.thread(task.thread_id)
        if thread.title is None:
            raise RuntimeError(f"GitHub thread {thread.id} has no pull request title")
        pull = await self.client.find_pull_request(repository, branch, base)
        if pull is None:
            pull = await self.client.create_pull_request(repository, branch, base, thread.title, body)
            logger.info(
                "thread pull request created", repository=repository, thread=thread.id, pull_request=pull.html_url
            )
        else:
            logger.info(
                "thread pull request reused", repository=repository, thread=thread.id, pull_request=pull.html_url
            )
        self.repository.set_pull_request(issue.thread_id, pull.number, pull.html_url)
        return pull.html_url

    async def complete_task(self, task: Task, job: Job) -> None:
        issue = self.repository.issue_for_thread(task.thread_id)
        if issue is None:
            raise RuntimeError(f"GitHub mapping missing for task {task.id}")
        if not job.pull_request_url:
            raise RuntimeError(f"task {task.id} completed without a pull request URL")
        await self._respond(
            issue,
            "addressed",
            self._task_anchor(issue, task),
            f"Issue addressed: {job.pull_request_url}\n\nTo make further changes, add a comment.",
        )
        self.tasks.set_state(task.id, TaskState.ADDRESSED)
        logger.info("task addressed", task=task.id, thread=task.thread_id, pull_request=job.pull_request_url)

    def _task_anchor(self, issue: StoredIssue, task: Task) -> str:
        messages = self.tasks.task_messages(task.id)
        if not messages:
            raise RuntimeError(f"task {task.id} has no messages")
        return self.repository.anchor_for_message(issue, messages[-1].id)

    @staticmethod
    def marker(repository: str, issue: int, outcome: str, anchor: str | int) -> str:
        digest = hashlib.sha256(f"{repository}:{issue}:{outcome}:{anchor}".encode()).hexdigest()[:24]
        return f"<!-- ocint:{digest} -->"

    async def _respond(self, issue: StoredIssue, outcome: str, anchor: str, text: str) -> None:
        marker = self.marker(issue.github_repository, issue.issue_number, outcome, anchor)
        comments = await self.client.comments(issue.github_repository, issue.issue_number)
        existing = next(
            (item for item in comments if item.user.login == self.config.github.agent_actor and marker in item.body),
            None,
        )
        response = existing or await self.client.post_comment(
            issue.github_repository, issue.issue_number, f"{text}\n\n{marker}"
        )
        message = self.tasks.upsert_message(
            issue.thread_id,
            f"github:{issue.github_repository}:comment:{response.id}",
            response.user.login,
            MessageClassification.AGENT_RESPONSE,
            response.body,
            response.created_at,
        )
        self.repository.upsert_comment(response.id, message.id, self._marker_from_body(response.body))

    @staticmethod
    def _marker_from_body(body: str) -> str:
        start = body.find("<!-- ocint:")
        end = body.find(" -->", start)
        return body[start : end + 4] if start >= 0 and end >= 0 else ""

    def _is_agent_comment(
        self,
        comment: GitHubComment,
        issue: StoredIssue,
        comments: tuple[GitHubComment, ...],
    ) -> bool:
        if comment.user.login != self.config.github.agent_actor:
            return False
        marker = self._marker_from_body(comment.body)
        if not marker:
            return False
        anchors = (
            self.repository.root_anchor(issue.github_issue_id),
            *(self.repository.comment_anchor(item.id) for item in comments),
        )
        return any(
            marker == self.marker(issue.github_repository, issue.issue_number, outcome, anchor)
            for outcome in ("addressed", "unauthorized", "closed-pr")
            for anchor in anchors
        )

    @staticmethod
    def _authorized(actor: str, repository: RepositoryConfig) -> bool:
        return not repository.actors or actor in repository.actors
