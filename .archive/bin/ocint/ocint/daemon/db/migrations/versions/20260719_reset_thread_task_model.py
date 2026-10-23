"""Reset thread workflow state for the provider-neutral model."""

import sqlalchemy as sa
from alembic import op

revision = "20260719_reset_thread_task_model"
down_revision = "20260719_add_thread_execution_job"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _drop_workflow()
    _create_current_workflow()


def downgrade() -> None:
    _drop_workflow()
    _create_previous_workflow()


def _drop_workflow() -> None:
    op.drop_index("ix_task_state", table_name="task")
    index = (
        "ix_thread_message_classification"
        if _has_index("ix_thread_message_classification")
        else "ix_thread_message_disposition"
    )
    op.drop_index(index, table_name="thread_message")
    op.drop_table("github_issue_comment")
    op.drop_table("github_issue")
    op.drop_table("task_job")
    op.drop_table("task_message")
    op.drop_table("task")
    op.drop_table("thread_message")
    op.drop_table("thread")


def _has_index(name: str) -> bool:
    return any(item["name"] == name for item in sa.inspect(op.get_bind()).get_indexes("thread_message"))


def _create_current_workflow() -> None:
    op.create_table(
        "thread",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.String(), nullable=False, unique=True),
        sa.Column("title", sa.Text()),
    )
    op.create_table(
        "thread_message",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("thread_id", sa.Integer(), sa.ForeignKey("thread.id"), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False, unique=True),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("classification", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source_created_at", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    _create_current_task_tables()
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
    _create_comment_table()
    op.create_index("ix_thread_message_classification", "thread_message", ["thread_id", "classification"])
    op.create_index("ix_task_state", "task", ["thread_id", "state"])


def _create_previous_workflow() -> None:
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
    _create_previous_task_tables()
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
    _create_comment_table()
    op.create_index("ix_thread_message_disposition", "thread_message", ["thread_id", "disposition"])
    op.create_index("ix_task_state", "task", ["thread_id", "state"])


def _create_current_task_tables() -> None:
    op.create_table(
        "task",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("thread_id", sa.Integer(), sa.ForeignKey("thread.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("predecessor_task_id", sa.Integer(), nullable=False),
        sa.Column("retry_claim_attempt", sa.Integer(), nullable=False),
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
        sa.UniqueConstraint("task_id", "attempt", name="uq_task_job_attempt"),
    )


def _create_previous_task_tables() -> None:
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


def _create_comment_table() -> None:
    op.create_table(
        "github_issue_comment",
        sa.Column("github_comment_id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("thread_message.id"), nullable=False, unique=True),
        sa.Column("marker", sa.String(), nullable=False),
    )
