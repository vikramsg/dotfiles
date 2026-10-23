"""Create the final single-process daemon job schema."""

import sqlalchemy as sa
from alembic import op

revision = "20260716_create_daemon_control"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("idempotency_key", sa.String(), nullable=False, unique=True),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("repository", sa.String(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("server_url", sa.Text(), nullable=False),
        sa.Column("worktree_path", sa.Text(), nullable=False),
        sa.Column("branch", sa.String(), nullable=False),
        sa.Column("base_revision", sa.String(), nullable=False),
        sa.Column("prompt_intended", sa.Integer(), nullable=False),
        sa.Column("prompt_submitted", sa.Integer(), nullable=False),
        sa.Column("commit_sha", sa.String(), nullable=False),
        sa.Column("pushed", sa.Integer(), nullable=False),
        sa.Column("pull_request_url", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index("ix_job_queue", "job", ["state", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_job_queue", table_name="job")
    op.drop_table("job")
