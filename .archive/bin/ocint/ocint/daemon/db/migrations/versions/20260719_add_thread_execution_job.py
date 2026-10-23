"""Create the daemon thread task schema."""

import sqlalchemy as sa
from alembic import op

revision = "20260719_add_thread_execution_job"
down_revision = "20260717_add_github_issues"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_github_issue_comment_pending", table_name="github_issue_comment")
    op.drop_table("github_issue_comment")
    op.drop_table("github_issue")
    op.create_table(
        "thread",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repository", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_thread_id", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("eligible", sa.Integer(), nullable=False),
        sa.Column("execution_job_id", sa.String(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.UniqueConstraint("source", "source_thread_id", name="uq_thread_source_identity"),
    )
    op.create_table(
        "thread_message",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("thread_id", sa.Integer(), sa.ForeignKey("thread.id"), nullable=False),
        sa.Column("source_message_id", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("actor_type", sa.String(), nullable=False),
        sa.Column("disposition", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source_created_at", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.UniqueConstraint("thread_id", "source_message_id", name="uq_thread_message_source_identity"),
    )
    op.create_table(
        "task",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("thread_id", sa.Integer(), sa.ForeignKey("thread.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("predecessor_task_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_table(
        "task_message",
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("task.id"), primary_key=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("thread_message.id"), primary_key=True),
    )
    op.create_table(
        "task_job",
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("task.id"), primary_key=True),
        sa.Column("job_id", sa.String(), sa.ForeignKey("job.id"), primary_key=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.UniqueConstraint("job_id", name="uq_task_job_job"),
    )
    op.create_table(
        "github_issue",
        sa.Column("thread_id", sa.Integer(), sa.ForeignKey("thread.id"), primary_key=True),
        sa.Column("github_repository", sa.String(), nullable=False),
        sa.Column("github_issue_id", sa.Integer(), nullable=False),
        sa.Column("issue_number", sa.Integer(), nullable=False),
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
    op.create_index("ix_thread_message_disposition", "thread_message", ["thread_id", "disposition"])
    op.create_index("ix_task_state", "task", ["thread_id", "state"])


def downgrade() -> None:
    op.drop_index("ix_task_state", table_name="task")
    op.drop_index("ix_thread_message_disposition", table_name="thread_message")
    op.drop_table("github_issue_comment")
    op.drop_table("github_issue")
    op.drop_table("task_job")
    op.drop_table("task_message")
    op.drop_table("task")
    op.drop_table("thread_message")
    op.drop_table("thread")
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
