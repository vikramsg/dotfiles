"""Include the conversation thread in coordinator message identity."""

from alembic import op

revision = "20260810_complete_coordinator_message_identity"
down_revision = "20260807_add_coordinator"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table("coordinator_event", recreate="always") as batch:
        batch.drop_constraint("uq_coordinator_event_message", type_="unique")
        batch.create_unique_constraint(
            "uq_coordinator_event_message",
            ["provider", "workspace_id", "channel_id", "thread_id", "message_id"],
        )
    op.execute("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    op.execute("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table("coordinator_event", recreate="always") as batch:
        batch.drop_constraint("uq_coordinator_event_message", type_="unique")
        batch.create_unique_constraint(
            "uq_coordinator_event_message",
            ["provider", "workspace_id", "channel_id", "message_id"],
        )
    op.execute("PRAGMA foreign_keys=ON")
