"""Persist human-readable job titles."""

import sqlalchemy as sa
from alembic import op

revision = "20260724_add_job_title"
down_revision = "20260724_decouple_github_source_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job", sa.Column("title", sa.Text(), nullable=False, server_default=""))
    op.execute("UPDATE job SET title = 'ocint: complete job ' || id WHERE title = ''")


def downgrade() -> None:
    with op.batch_alter_table("job") as batch:
        batch.drop_column("title")
