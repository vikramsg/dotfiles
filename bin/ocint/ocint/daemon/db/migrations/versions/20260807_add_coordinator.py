"""Add the isolated coordinator durable workflow."""

import sqlalchemy as sa
from alembic import op

revision = "20260807_add_coordinator"
down_revision = "20260724_add_slack"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coordinator_event",
        sa.Column("event_id", sa.String(), primary_key=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("channel_id", sa.String(), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("message_id", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_created_at", sa.String(), nullable=False),
        sa.Column("source_order_at", sa.Integer(), nullable=False),
        sa.Column("message_kind", sa.String(), nullable=False),
        sa.Column("managed_prompt", sa.Text(), nullable=False),
        sa.Column("disposition", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.UniqueConstraint(
            "provider", "workspace_id", "channel_id", "message_id", name="uq_coordinator_event_message"
        ),
    )
    op.create_table(
        "coordinator_conversation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("channel_id", sa.String(), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("opencode_session_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.UniqueConstraint(
            "provider", "workspace_id", "channel_id", "thread_id", name="uq_coordinator_conversation_identity"
        ),
    )
    op.create_table(
        "coordinator_turn",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(), sa.ForeignKey("coordinator_event.event_id"), nullable=False, unique=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("coordinator_conversation.id"), nullable=False),
        sa.Column("source_order_at", sa.Integer(), nullable=False),
        sa.Column("source_order_tiebreaker", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("managed_prompt", sa.Text(), nullable=False),
        sa.Column("opencode_user_message_id", sa.String(), nullable=False, unique=True),
        sa.Column("assistant_message_id", sa.String(), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("retry_not_before", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_table(
        "coordinator_delivery",
        sa.Column("turn_id", sa.Integer(), sa.ForeignKey("coordinator_turn.id"), primary_key=True),
        sa.Column("chunk_index", sa.Integer(), primary_key=True),
        sa.Column("client_msg_id", sa.String(), nullable=False, unique=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("provider_message_id", sa.String(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("retry_not_before", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index(
        "ix_coordinator_event_conversation",
        "coordinator_event",
        ["provider", "workspace_id", "channel_id", "thread_id"],
    )
    op.create_index(
        "ix_coordinator_turn_ready",
        "coordinator_turn",
        ["state", "retry_not_before", "source_order_at", "source_order_tiebreaker"],
    )
    op.create_index("ix_coordinator_delivery_ready", "coordinator_delivery", ["state", "retry_not_before"])


def downgrade() -> None:
    op.drop_index("ix_coordinator_delivery_ready", table_name="coordinator_delivery")
    op.drop_index("ix_coordinator_turn_ready", table_name="coordinator_turn")
    op.drop_index("ix_coordinator_event_conversation", table_name="coordinator_event")
    op.drop_table("coordinator_delivery")
    op.drop_table("coordinator_turn")
    op.drop_table("coordinator_conversation")
    op.drop_table("coordinator_event")
