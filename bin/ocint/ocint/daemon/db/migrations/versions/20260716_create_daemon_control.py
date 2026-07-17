"""Create the final single-process daemon job schema."""

from alembic import op
from ocint.daemon.db.schema import metadata

revision = "20260716_create_daemon_control"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata.create_all(op.get_bind())


def downgrade() -> None:
    metadata.drop_all(op.get_bind())
