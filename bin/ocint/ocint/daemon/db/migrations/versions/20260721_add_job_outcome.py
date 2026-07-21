"""Add reply and pull-request job outcomes."""

import sqlalchemy as sa
from alembic import op

revision = "20260721_add_job_outcome"
down_revision = "20260719_reset_thread_task_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job", sa.Column("outcome", sa.String(), nullable=False, server_default="pending"))
    op.add_column("job", sa.Column("response", sa.Text(), nullable=False, server_default=""))
    op.execute("UPDATE job SET outcome = 'pull_request' WHERE pull_request_url <> ''")


def downgrade() -> None:
    op.drop_column("job", "response")
    op.drop_column("job", "outcome")
