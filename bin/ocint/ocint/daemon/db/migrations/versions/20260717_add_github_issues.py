"""Add durable GitHub issue and comment state without changing jobs."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_add_github_issues"
down_revision = "20260716_create_daemon_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "github_issue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repository", sa.String(), nullable=False),
        sa.Column("github_repository", sa.String(), nullable=False),
        sa.Column("github_issue_id", sa.Integer(), nullable=False),
        sa.Column("issue_number", sa.Integer(), nullable=False),
        sa.Column("issue_author", sa.String(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("job_id", sa.String(), sa.ForeignKey("job.id"), nullable=False, unique=True),
        sa.Column("pull_request_number", sa.Integer(), nullable=False),
        sa.Column("pull_request_url", sa.Text(), nullable=False),
        sa.Column("initial_state", sa.String(), nullable=False),
        sa.Column("active_anchor_comment_id", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.UniqueConstraint("repository", "github_issue_id", name="uq_github_issue_repository_issue"),
    )
    op.create_table(
        "github_issue_comment",
        sa.Column("github_comment_id", sa.Integer(), primary_key=True),
        sa.Column("issue_id", sa.Integer(), sa.ForeignKey("github_issue.id"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("actor_login", sa.String(), nullable=False),
        sa.Column("actor_type", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("github_created_at", sa.String(), nullable=False),
        sa.Column("marker", sa.String(), nullable=False),
        sa.Column("agent_response_comment_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index("ix_github_issue_comment_pending", "github_issue_comment", ["issue_id", "state"])


def downgrade() -> None:
    op.drop_index("ix_github_issue_comment_pending", table_name="github_issue_comment")
    op.drop_table("github_issue_comment")
    op.drop_table("github_issue")
