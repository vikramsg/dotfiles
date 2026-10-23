"""Add provider-neutral PR ownership and durable Slack source state.

Downgrade intentionally removes Slack polling/reply state and PR ownership.
The additive upgrade preserves and backfills established GitHub workflow data.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260724_add_slack"
down_revision = "20260724_add_job_title"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pull_request_ownership",
        sa.Column("source_thread_id", sa.String(), primary_key=True),
        sa.Column("repository", sa.String(), primary_key=True),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
    )
    op.execute(
        "INSERT INTO pull_request_ownership (source_thread_id, repository, number, url) SELECT source_id, github_repository, pull_request_number, pull_request_url FROM github_issue WHERE pull_request_number != 0"
    )
    op.create_table(
        "slack_channel",
        sa.Column("channel_id", sa.String(), primary_key=True),
        sa.Column("watermark", sa.String(), nullable=False),
        sa.Column("retry_not_before", sa.String(), nullable=False),
    )
    op.create_table(
        "slack_thread",
        sa.Column("channel_id", sa.String(), primary_key=True),
        sa.Column("root_ts", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("logical_source_id", sa.String(), nullable=False),
        sa.Column("root_identity", sa.Text(), nullable=False, unique=True),
        sa.Column("configured_repository", sa.String(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("authorized", sa.Integer(), nullable=False),
        sa.Column("closed", sa.Integer(), nullable=False),
        sa.Column("reopen_root", sa.Integer(), nullable=False),
    )
    op.create_table(
        "slack_message",
        sa.Column("channel_id", sa.String(), primary_key=True),
        sa.Column("ts", sa.String(), primary_key=True),
        sa.Column("root_ts", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("classification", sa.String(), nullable=False),
    )
    op.create_table(
        "slack_reply",
        sa.Column("idempotency_key", sa.String(), primary_key=True),
        sa.Column("channel_id", sa.String(), nullable=False),
        sa.Column("ts", sa.String(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("slack_reply")
    op.drop_table("slack_message")
    op.drop_table("slack_thread")
    op.drop_table("slack_channel")
    op.drop_table("pull_request_ownership")
