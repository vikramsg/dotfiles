import hashlib
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from ocint.daemon.github.config import GitHubConfig
from ocint.daemon.github.models import (
    GitHubComment,
    GitHubComments,
    GitHubIssueIds,
    GitHubIssues,
    GitHubPullRequest,
    GitHubRepositoryPolicies,
    StoredIssue,
)
from ocint.daemon.github.repository import GitHubRepository
from ocint.daemon.logging import get_logger
from ocint.daemon.models import (
    GitHubLogin,
    MessageClassification,
    ObservedMessage,
    ObservedMessages,
    PublicationRequest,
    PublicationResult,
    PublishedPublication,
    RefusedPublication,
    ReplyRequest,
    ThreadObservation,
    ThreadObservations,
    ThreadOrigin,
)

logger = get_logger("github")


@runtime_checkable
class GitHubTransport(Protocol):
    async def issues(self, repository: str, label: str) -> GitHubIssues: ...
    async def comments(self, repository: str, number: int) -> GitHubComments: ...
    async def pull_request(self, repository: str, number: int) -> GitHubPullRequest: ...
    async def find_pull_request(self, repository: str, branch: str, base: str) -> GitHubPullRequest | None: ...
    async def create_pull_request(
        self, repository: str, branch: str, base: str, title: str, body: str
    ) -> GitHubPullRequest: ...
    async def post_comment(self, repository: str, number: int, body: str) -> GitHubComment: ...


class GitHubContext(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    config: GitHubConfig
    repositories: GitHubRepositoryPolicies
    client: GitHubTransport
    repository: GitHubRepository


class GitHubService(BaseModel):
    """Provide GitHub operations through daemon consumer protocols.

    `open_github_service` constructs this concrete service and yields it to the
    daemon CLI. The CLI injects the same instance into `TaskCoordinator` as its
    consumer-owned `ThreadSource` protocol and into `JobExecutor` as its
    consumer-owned `PullRequestPublisher` protocol. Neither consumer imports or
    constructs this class. GitHub exchanges typed DTOs and never accesses task
    models, task repositories, or task state.
    """

    model_config = ConfigDict(frozen=True)

    context: GitHubContext

    async def observe(self) -> ThreadObservations:
        observations: list[ThreadObservation] = []
        for configured in self.context.repositories.root:
            issues = await self.context.client.issues(configured.github_repository, self.context.config.issue_label)
            eligible_ids: list[int] = []
            for issue in issues.root:
                source_id = _thread_source_id(configured.github_repository, issue.id)
                root_source_id = _issue_source_id(configured.github_repository, issue.id)
                authorized = _is_authorized(issue.user.login, configured.actors)
                if authorized:
                    eligible_ids.append(issue.id)
                stored = self.context.repository.upsert_issue(
                    source_id,
                    root_source_id,
                    configured.name,
                    configured.github_repository,
                    issue.id,
                    issue.number,
                    authorized,
                )
                comments = await self.context.client.comments(configured.github_repository, issue.number)
                messages = [
                    ObservedMessage(
                        source_id=root_source_id,
                        actor=issue.user.login,
                        classification=(
                            MessageClassification.ACTIONABLE if authorized else MessageClassification.UNAUTHORIZED
                        ),
                        body=issue.body,
                        source_created_at=issue.created_at,
                    )
                ]
                for comment in comments.root:
                    comment_source_id = _comment_source_id(configured.github_repository, comment.id)
                    classification = _classification(self.context, comment, stored, comments, configured.actors)
                    self.context.repository.upsert_comment(
                        comment_source_id,
                        source_id,
                        comment.id,
                        _marker_from_body(comment.body),
                    )
                    messages.append(
                        ObservedMessage(
                            source_id=comment_source_id,
                            actor=comment.user.login,
                            classification=classification,
                            body=comment.body,
                            source_created_at=comment.created_at,
                        )
                    )
                observations.append(
                    ThreadObservation(
                        source_id=source_id,
                        configured_repository=configured.name,
                        title=issue.title,
                        eligible=authorized,
                        messages=ObservedMessages(root=messages),
                    )
                )
            self.context.repository.synchronize(configured.name, GitHubIssueIds(root=eligible_ids))
            observed_sources = {item.source_id for item in observations}
            observations.extend(
                ThreadObservation(
                    source_id=source_id,
                    configured_repository=configured.name,
                    title="",
                    eligible=False,
                    messages=ObservedMessages(root=[]),
                )
                for source_id in self.context.repository.ineligible_sources(configured.name)
                if source_id not in observed_sources
            )
        return ThreadObservations(root=observations)

    async def reply(self, request: ReplyRequest) -> ObservedMessage:
        issue = self.context.repository.issue(request.source_thread_id)
        if issue is None:
            raise RuntimeError(f"GitHub mapping missing for source {request.source_thread_id}")
        anchor = self.context.repository.anchor_for_source(issue, request.source_anchor_id)
        mk = marker(issue.github_repository, issue.issue_number, request.outcome.value, anchor)
        comments = await self.context.client.comments(issue.github_repository, issue.issue_number)
        existing = next(
            (item for item in comments.root if item.user.login == self.context.config.agent_actor and mk in item.body),
            None,
        )
        response = existing or await self.context.client.post_comment(
            issue.github_repository, issue.issue_number, f"{request.text}\n\n{mk}"
        )
        source_id = _comment_source_id(issue.github_repository, response.id)
        self.context.repository.upsert_comment(
            source_id, issue.source_id, response.id, _marker_from_body(response.body)
        )
        return ObservedMessage(
            source_id=source_id,
            actor=response.user.login,
            classification=MessageClassification.AGENT_RESPONSE,
            body=response.body,
            source_created_at=response.created_at,
        )

    async def publish(self, request: PublicationRequest) -> PublicationResult:
        issue = (
            self.context.repository.issue(request.origin.source_thread_id)
            if isinstance(request.origin, ThreadOrigin)
            else None
        )
        if issue is not None and issue.pull_request_number:
            pull = await self.context.client.pull_request(request.repository, issue.pull_request_number)
            if pull.state != "open" or pull.merged:
                return RefusedPublication()
            return PublishedPublication(url=pull.html_url)
        pull = await self.context.client.find_pull_request(request.repository, request.branch, request.base)
        if pull is None:
            pull = await self.context.client.create_pull_request(
                request.repository, request.branch, request.base, request.title, request.body
            )
        if issue is not None:
            self.context.repository.set_pull_request(issue.source_id, pull.number, pull.html_url)
        return PublishedPublication(url=pull.html_url)


def marker(repository: str, issue: int, outcome: str, anchor: str | int) -> str:
    digest = hashlib.sha256(f"{repository}:{issue}:{outcome}:{anchor}".encode()).hexdigest()[:24]
    return f"<!-- ocint:{digest} -->"


def _is_authorized(actor: GitHubLogin, actors: frozenset[GitHubLogin]) -> bool:
    return not actors or actor in actors


def _classification(
    context: GitHubContext,
    comment: GitHubComment,
    issue: StoredIssue,
    comments: GitHubComments,
    actors: frozenset[GitHubLogin],
) -> MessageClassification:
    if _is_agent_comment(context, comment, issue, comments):
        return MessageClassification.AGENT_RESPONSE
    return (
        MessageClassification.ACTIONABLE
        if _is_authorized(comment.user.login, actors)
        else MessageClassification.UNAUTHORIZED
    )


def _is_agent_comment(
    context: GitHubContext, comment: GitHubComment, issue: StoredIssue, comments: GitHubComments
) -> bool:
    if comment.user.login != context.config.agent_actor:
        return False
    current = _marker_from_body(comment.body)
    if not current:
        return False
    anchors = [
        context.repository.root_anchor(issue.github_issue_id),
        *(context.repository.comment_anchor(item.id) for item in comments.root),
    ]
    return any(
        current == marker(issue.github_repository, issue.issue_number, outcome, anchor)
        for outcome in ("addressed", "unauthorized", "closed-pr")
        for anchor in anchors
    )


def _marker_from_body(body: str) -> str:
    start = body.find("<!-- ocint:")
    end = body.find(" -->", start)
    return body[start : end + 4] if start >= 0 and end >= 0 else ""


def _thread_source_id(repository: str, issue_id: int) -> str:
    return f"github:{repository}:{issue_id}"


def _issue_source_id(repository: str, issue_id: int) -> str:
    return f"github:{repository}:issue:{issue_id}"


def _comment_source_id(repository: str, comment_id: int) -> str:
    return f"github:{repository}:comment:{comment_id}"
