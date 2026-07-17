from datetime import UTC, datetime

from sqlalchemy import Engine, insert, or_, select, update
from sqlalchemy.engine import RowMapping

from ocint.daemon.db.schema import github_issue, github_issue_comment
from ocint.daemon.github.models import ActorType, CommentState, GitHubComment, GitHubIssue, StoredComment, StoredIssue


class GitHubRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def issue(self, repository: str, github_repository: str, value: GitHubIssue, job_id: str) -> StoredIssue:
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(github_issue).where(
                        github_issue.c.repository == repository,
                        github_issue.c.github_issue_id == value.id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                now = datetime.now(UTC).isoformat()
                connection.execute(
                    insert(github_issue).values(
                        repository=repository,
                        github_repository=github_repository,
                        github_issue_id=value.id,
                        issue_number=value.number,
                        issue_author=value.user.login,
                        title=value.title,
                        body=value.body,
                        job_id=job_id,
                        pull_request_number=0,
                        pull_request_url="",
                        initial_state="pending",
                        active_anchor_comment_id=0,
                        error="",
                        created_at=now,
                        updated_at=now,
                    )
                )
                row = (
                    connection.execute(
                        select(github_issue).where(
                            github_issue.c.repository == repository,
                            github_issue.c.github_issue_id == value.id,
                        )
                    )
                    .mappings()
                    .one()
                )
        return self._issue(row)

    def find_issue(self, repository: str, github_issue_id: int) -> StoredIssue | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(github_issue).where(
                        github_issue.c.repository == repository,
                        github_issue.c.github_issue_id == github_issue_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
        return self._issue(row) if row is not None else None

    def issue_for_job(self, job_id: str) -> StoredIssue:
        with self.engine.connect() as connection:
            row = connection.execute(select(github_issue).where(github_issue.c.job_id == job_id)).mappings().one()
        return self._issue(row)

    def find_issue_for_job(self, job_id: str) -> StoredIssue | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(select(github_issue).where(github_issue.c.job_id == job_id)).mappings().one_or_none()
            )
        return self._issue(row) if row is not None else None

    def store_comment(
        self, issue_id: int, value: GitHubComment, actor_type: ActorType, state: CommentState, marker: str = ""
    ) -> StoredComment:
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(github_issue_comment).where(github_issue_comment.c.github_comment_id == value.id)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                now = datetime.now(UTC).isoformat()
                connection.execute(
                    insert(github_issue_comment).values(
                        github_comment_id=value.id,
                        issue_id=issue_id,
                        body=value.body,
                        actor_login=value.user.login,
                        actor_type=actor_type.value,
                        state=state.value,
                        github_created_at=value.created_at,
                        marker=marker,
                        agent_response_comment_id=value.id if actor_type is ActorType.AGENT else 0,
                        created_at=now,
                        updated_at=now,
                    )
                )
                row = (
                    connection.execute(
                        select(github_issue_comment).where(github_issue_comment.c.github_comment_id == value.id)
                    )
                    .mappings()
                    .one()
                )
        return self._comment(row)

    def pending(self, issue_id: int) -> tuple[StoredComment, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(github_issue_comment)
                .where(
                    github_issue_comment.c.issue_id == issue_id,
                    github_issue_comment.c.actor_type == ActorType.HUMAN.value,
                    github_issue_comment.c.state == CommentState.PENDING.value,
                )
                .order_by(github_issue_comment.c.github_created_at, github_issue_comment.c.github_comment_id)
            ).mappings()
            return tuple(self._comment(row) for row in rows)

    def active(self, issue_id: int, anchor: int) -> tuple[StoredComment, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(github_issue_comment)
                .where(
                    github_issue_comment.c.issue_id == issue_id,
                    github_issue_comment.c.actor_type == ActorType.HUMAN.value,
                    or_(
                        github_issue_comment.c.state == CommentState.BATCHED.value,
                        github_issue_comment.c.github_comment_id == anchor,
                    ),
                )
                .order_by(github_issue_comment.c.github_created_at, github_issue_comment.c.github_comment_id)
            ).mappings()
            return tuple(self._comment(row) for row in rows)

    def activate(self, issue_id: int, comments: tuple[StoredComment, ...]) -> None:
        if not comments:
            return
        now = datetime.now(UTC).isoformat()
        anchor = comments[-1].github_comment_id
        with self.engine.begin() as connection:
            for comment in comments[:-1]:
                connection.execute(
                    update(github_issue_comment)
                    .where(github_issue_comment.c.github_comment_id == comment.github_comment_id)
                    .values(state=CommentState.BATCHED.value, updated_at=now)
                )
            connection.execute(
                update(github_issue)
                .where(github_issue.c.id == issue_id)
                .values(active_anchor_comment_id=anchor, updated_at=now)
            )

    def finalize(self, issue_id: int, state: CommentState) -> None:
        with self.engine.begin() as connection:
            issue = connection.execute(select(github_issue).where(github_issue.c.id == issue_id)).mappings().one()
            anchor = int(issue["active_anchor_comment_id"])
            if anchor:
                connection.execute(
                    update(github_issue_comment)
                    .where(
                        github_issue_comment.c.issue_id == issue_id,
                        or_(
                            github_issue_comment.c.state == CommentState.BATCHED.value,
                            github_issue_comment.c.github_comment_id == anchor,
                        ),
                    )
                    .values(state=state.value, updated_at=datetime.now(UTC).isoformat())
                )
            connection.execute(
                update(github_issue)
                .where(github_issue.c.id == issue_id)
                .values(initial_state=state.value, active_anchor_comment_id=0, updated_at=datetime.now(UTC).isoformat())
            )

    def set_pull_request(self, issue_id: int, number: int, url: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(github_issue)
                .where(github_issue.c.id == issue_id)
                .values(pull_request_number=number, pull_request_url=url, updated_at=datetime.now(UTC).isoformat())
            )

    def set_error(self, issue_id: int, error: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(github_issue)
                .where(github_issue.c.id == issue_id)
                .values(error=error, updated_at=datetime.now(UTC).isoformat())
            )

    def _issue(self, row: RowMapping) -> StoredIssue:
        return StoredIssue(**{field: row[field] for field in StoredIssue.model_fields})

    def _comment(self, row: RowMapping) -> StoredComment:
        return StoredComment(**{field: row[field] for field in StoredComment.model_fields})
