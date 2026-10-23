from sqlalchemy import Engine, insert, select, update
from sqlalchemy.engine import RowMapping

from ocint.daemon.db.schema import github_issue, github_issue_comment
from ocint.daemon.github.models import GitHubIssueIds, StoredComment, StoredIssue


class GitHubRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def upsert_issue(
        self,
        source_id: str,
        root_source_id: str,
        configured_repository: str,
        github_repository: str,
        github_issue_id: int,
        issue_number: int,
        eligible: bool,
    ) -> StoredIssue:
        with self.engine.begin() as connection:
            identity = github_issue.c.source_id == source_id
            row = connection.execute(select(github_issue).where(identity)).mappings().one_or_none()
            values = {
                "root_source_id": root_source_id,
                "configured_repository": configured_repository,
                "github_repository": github_repository,
                "github_issue_id": github_issue_id,
                "issue_number": issue_number,
                "eligible": eligible,
            }
            if row is None:
                connection.execute(
                    insert(github_issue).values(
                        source_id=source_id,
                        pull_request_number=0,
                        pull_request_url="",
                        **values,
                    )
                )
            else:
                connection.execute(update(github_issue).where(identity).values(**values))
            row = connection.execute(select(github_issue).where(identity)).mappings().one()
        return self._issue(row)

    def synchronize(self, configured_repository: str, eligible_issue_ids: GitHubIssueIds) -> None:
        with self.engine.begin() as connection:
            query = update(github_issue).where(github_issue.c.configured_repository == configured_repository)
            if eligible_issue_ids.root:
                query = query.where(~github_issue.c.github_issue_id.in_(eligible_issue_ids.root))
            connection.execute(query.values(eligible=False))

    def ineligible_sources(self, configured_repository: str) -> list[str]:
        with self.engine.connect() as connection:
            values = connection.execute(
                select(github_issue.c.source_id).where(
                    github_issue.c.configured_repository == configured_repository,
                    github_issue.c.eligible == 0,
                )
            ).scalars()
            return [str(value) for value in values]

    def issue(self, source_id: str) -> StoredIssue | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(select(github_issue).where(github_issue.c.source_id == source_id))
                .mappings()
                .one_or_none()
            )
        return self._issue(row) if row is not None else None

    def set_pull_request(self, source_id: str, number: int, url: str) -> StoredIssue:
        with self.engine.begin() as connection:
            connection.execute(
                update(github_issue)
                .where(github_issue.c.source_id == source_id)
                .values(pull_request_number=number, pull_request_url=url)
            )
        issue = self.issue(source_id)
        if issue is None:
            raise ValueError(f"GitHub issue mapping not found for source {source_id}")
        return issue

    def anchor_for_source(self, issue: StoredIssue, source_id: str) -> str:
        if source_id == issue.root_source_id:
            return self.root_anchor(issue.github_issue_id)
        with self.engine.connect() as connection:
            value = connection.execute(
                select(github_issue_comment.c.github_comment_id).where(github_issue_comment.c.source_id == source_id)
            ).scalar_one_or_none()
        if value is None:
            raise ValueError(f"GitHub comment mapping not found for source {source_id}")
        return self.comment_anchor(int(value))

    @staticmethod
    def root_anchor(github_issue_id: int) -> str:
        return f"issue:{github_issue_id}"

    @staticmethod
    def comment_anchor(github_comment_id: int) -> str:
        return f"comment:{github_comment_id}"

    def upsert_comment(
        self, source_id: str, issue_source_id: str, github_comment_id: int, marker: str
    ) -> StoredComment:
        with self.engine.begin() as connection:
            identity = github_issue_comment.c.source_id == source_id
            row = connection.execute(select(github_issue_comment).where(identity)).mappings().one_or_none()
            if row is None:
                connection.execute(
                    insert(github_issue_comment).values(
                        source_id=source_id,
                        issue_source_id=issue_source_id,
                        github_comment_id=github_comment_id,
                        marker=marker,
                    )
                )
            row = connection.execute(select(github_issue_comment).where(identity)).mappings().one()
        return self._comment(row)

    @staticmethod
    def _issue(row: RowMapping) -> StoredIssue:
        return StoredIssue(**{field: row[field] for field in StoredIssue.model_fields})

    @staticmethod
    def _comment(row: RowMapping) -> StoredComment:
        return StoredComment(**{field: row[field] for field in StoredComment.model_fields})
