"""Decouple GitHub source state from task persistence IDs."""

import sqlalchemy as sa
from alembic import op

revision = "20260724_decouple_github_source_state"
down_revision = "20260719_reset_thread_task_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job", sa.Column("origin_kind", sa.String(), nullable=False, server_default="direct"))
    op.add_column("job", sa.Column("origin_source_thread_id", sa.String(), nullable=False, server_default=""))
    op.add_column("job", sa.Column("origin_source_anchor_id", sa.String(), nullable=False, server_default=""))
    op.add_column("job", sa.Column("publication_refusal", sa.String(), nullable=False, server_default=""))
    op.add_column("thread", sa.Column("configured_repository", sa.String(), nullable=False, server_default=""))
    op.add_column("thread", sa.Column("eligible", sa.Integer(), nullable=False, server_default="0"))
    op.execute(
        "UPDATE thread SET configured_repository = COALESCE((SELECT configured_repository FROM github_issue "
        "WHERE github_issue.thread_id = thread.id), ''), eligible = COALESCE((SELECT eligible FROM github_issue "
        "WHERE github_issue.thread_id = thread.id), 0)"
    )

    op.rename_table("github_issue", "github_issue_task_link")
    op.rename_table("github_issue_comment", "github_comment_task_link")
    _create_source_tables()
    op.execute(
        "INSERT INTO github_issue (source_id, root_source_id, configured_repository, github_repository, "
        "github_issue_id, issue_number, eligible, pull_request_number, pull_request_url) "
        "SELECT t.source_id, m.source_id, g.configured_repository, g.github_repository, g.github_issue_id, "
        "g.issue_number, g.eligible, g.pull_request_number, g.pull_request_url FROM github_issue_task_link g "
        "JOIN thread t ON t.id = g.thread_id JOIN thread_message m ON m.id = g.root_message_id"
    )
    op.execute(
        "INSERT INTO github_issue_comment (source_id, issue_source_id, github_comment_id, marker) "
        "SELECT m.source_id, t.source_id, c.github_comment_id, c.marker FROM github_comment_task_link c "
        "JOIN thread_message m ON m.id = c.message_id JOIN thread t ON t.id = m.thread_id"
    )
    op.drop_table("github_comment_task_link")
    op.drop_table("github_issue_task_link")


def downgrade() -> None:
    op.rename_table("github_issue", "github_issue_source_state")
    op.rename_table("github_issue_comment", "github_comment_source_state")
    op.create_table(
        "github_issue",
        sa.Column("thread_id", sa.Integer(), sa.ForeignKey("thread.id"), primary_key=True),
        sa.Column("root_message_id", sa.Integer(), sa.ForeignKey("thread_message.id"), nullable=False, unique=True),
        sa.Column("configured_repository", sa.String(), nullable=False),
        sa.Column("github_repository", sa.String(), nullable=False),
        sa.Column("github_issue_id", sa.Integer(), nullable=False),
        sa.Column("issue_number", sa.Integer(), nullable=False),
        sa.Column("eligible", sa.Integer(), nullable=False),
        sa.Column("pull_request_number", sa.Integer(), nullable=False),
        sa.Column("pull_request_url", sa.Text(), nullable=False),
        sa.UniqueConstraint("github_repository", "github_issue_id", name="uq_github_issue_identity"),
    )
    op.create_table(
        "github_issue_comment",
        sa.Column("github_comment_id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("thread_message.id"), nullable=False, unique=True),
        sa.Column("marker", sa.String(), nullable=False),
    )
    op.execute(
        "INSERT INTO github_issue SELECT t.id, m.id, g.configured_repository, g.github_repository, "
        "g.github_issue_id, g.issue_number, g.eligible, g.pull_request_number, g.pull_request_url "
        "FROM github_issue_source_state g JOIN thread t ON t.source_id = g.source_id "
        "JOIN thread_message m ON m.source_id = g.root_source_id"
    )
    op.execute(
        "INSERT INTO github_issue_comment SELECT c.github_comment_id, m.id, c.marker "
        "FROM github_comment_source_state c JOIN thread_message m ON m.source_id = c.source_id"
    )
    op.drop_table("github_comment_source_state")
    op.drop_table("github_issue_source_state")
    with op.batch_alter_table("thread") as batch:
        batch.drop_column("eligible")
        batch.drop_column("configured_repository")
    with op.batch_alter_table("job") as batch:
        batch.drop_column("publication_refusal")
        batch.drop_column("origin_source_anchor_id")
        batch.drop_column("origin_source_thread_id")
        batch.drop_column("origin_kind")


def _create_source_tables() -> None:
    op.create_table(
        "github_issue",
        sa.Column("source_id", sa.String(), primary_key=True),
        sa.Column("root_source_id", sa.String(), nullable=False, unique=True),
        sa.Column("configured_repository", sa.String(), nullable=False),
        sa.Column("github_repository", sa.String(), nullable=False),
        sa.Column("github_issue_id", sa.Integer(), nullable=False),
        sa.Column("issue_number", sa.Integer(), nullable=False),
        sa.Column("eligible", sa.Integer(), nullable=False),
        sa.Column("pull_request_number", sa.Integer(), nullable=False),
        sa.Column("pull_request_url", sa.Text(), nullable=False),
        sa.UniqueConstraint("github_repository", "github_issue_id", name="uq_github_issue_identity"),
    )
    op.create_table(
        "github_issue_comment",
        sa.Column("source_id", sa.String(), primary_key=True),
        sa.Column("issue_source_id", sa.String(), sa.ForeignKey("github_issue.source_id"), nullable=False),
        sa.Column("github_comment_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("marker", sa.String(), nullable=False),
    )
