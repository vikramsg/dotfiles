from sqlalchemy import Engine, insert, select, update
from sqlalchemy.engine import RowMapping

from ocint.daemon.db.schema import github_issue, github_issue_comment
from ocint.daemon.github.models import StoredComment, StoredIssue


class GitHubRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def upsert_issue(
        self,
        thread_id: int,
        root_message_id: int,
        configured_repository: str,
        github_repository: str,
        github_issue_id: int,
        issue_number: int,
        eligible: bool,
    ) -> StoredIssue:
        with self.engine.begin() as connection:
            row = (
                connection.execute(select(github_issue).where(github_issue.c.thread_id == thread_id))
                .mappings()
                .one_or_none()
            )
            if row is None:
                connection.execute(
                    insert(github_issue).values(
                        thread_id=thread_id,
                        root_message_id=root_message_id,
                        configured_repository=configured_repository,
                        github_repository=github_repository,
                        github_issue_id=github_issue_id,
                        issue_number=issue_number,
                        eligible=eligible,
                        pull_request_number=0,
                        pull_request_url="",
                    )
                )
                row = (
                    connection.execute(select(github_issue).where(github_issue.c.thread_id == thread_id))
                    .mappings()
                    .one()
                )
            else:
                connection.execute(
                    update(github_issue)
                    .where(github_issue.c.thread_id == thread_id)
                    .values(
                        root_message_id=root_message_id,
                        configured_repository=configured_repository,
                        github_repository=github_repository,
                        github_issue_id=github_issue_id,
                        issue_number=issue_number,
                        eligible=eligible,
                    )
                )
                row = (
                    connection.execute(select(github_issue).where(github_issue.c.thread_id == thread_id))
                    .mappings()
                    .one()
                )
        return self._issue(row)

    def synchronize(self, configured_repository: str, eligible_issue_ids: tuple[int, ...]) -> None:
        with self.engine.begin() as connection:
            query = update(github_issue).where(github_issue.c.configured_repository == configured_repository)
            if eligible_issue_ids:
                query = query.where(~github_issue.c.github_issue_id.in_(eligible_issue_ids))
            connection.execute(query.values(eligible=False))

    def issue_for_thread(self, thread_id: int) -> StoredIssue | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(select(github_issue).where(github_issue.c.thread_id == thread_id))
                .mappings()
                .one_or_none()
            )
        return self._issue(row) if row is not None else None

    def set_pull_request(self, thread_id: int, number: int, url: str) -> StoredIssue:
        with self.engine.begin() as connection:
            connection.execute(
                update(github_issue)
                .where(github_issue.c.thread_id == thread_id)
                .values(pull_request_number=number, pull_request_url=url)
            )
        issue = self.issue_for_thread(thread_id)
        if issue is None:
            raise ValueError(f"GitHub issue mapping not found for thread {thread_id}")
        return issue

    def anchor_for_message(self, issue: StoredIssue, message_id: int) -> str:
        if message_id == issue.root_message_id:
            return self.root_anchor(issue.github_issue_id)
        with self.engine.connect() as connection:
            github_comment_id = connection.execute(
                select(github_issue_comment.c.github_comment_id).where(github_issue_comment.c.message_id == message_id)
            ).scalar_one_or_none()
        if github_comment_id is None:
            raise ValueError(f"GitHub comment mapping not found for message {message_id}")
        return self.comment_anchor(int(github_comment_id))

    @staticmethod
    def root_anchor(github_issue_id: int) -> str:
        return f"issue:{github_issue_id}"

    @staticmethod
    def comment_anchor(github_comment_id: int) -> str:
        return f"comment:{github_comment_id}"

    def upsert_comment(self, github_comment_id: int, message_id: int, marker: str) -> StoredComment:
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(github_issue_comment).where(github_issue_comment.c.github_comment_id == github_comment_id)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                connection.execute(
                    insert(github_issue_comment).values(
                        github_comment_id=github_comment_id,
                        message_id=message_id,
                        marker=marker,
                    )
                )
                row = (
                    connection.execute(
                        select(github_issue_comment).where(
                            github_issue_comment.c.github_comment_id == github_comment_id
                        )
                    )
                    .mappings()
                    .one()
                )
        return self._comment(row)

    @staticmethod
    def _issue(row: RowMapping) -> StoredIssue:
        return StoredIssue(**{field: row[field] for field in StoredIssue.model_fields})

    @staticmethod
    def _comment(row: RowMapping) -> StoredComment:
        return StoredComment(**{field: row[field] for field in StoredComment.model_fields})
