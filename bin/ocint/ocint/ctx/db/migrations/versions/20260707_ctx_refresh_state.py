"""move ctx refresh metadata into ctx-owned refresh state

Revision ID: 20260707_ctx_refresh_state
Revises: 20260704_create_ctx_index
Create Date: 2026-07-07
"""

from alembic import op
from sqlalchemy import BigInteger, Column, ForeignKey, Integer, String, Text, text

from ocint.ctx.sql.models import default_ctx_sql_config, stable_view_create_statements

revision = "20260707_ctx_refresh_state"
down_revision = "20260704_create_ctx_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    _drop_stable_views()
    if not _table_exists("ctx_refresh_state"):
        op.create_table(
            "ctx_refresh_state",
            Column("source_id", Integer, ForeignKey("ctx_source.id", ondelete="CASCADE"), primary_key=True),
            Column("latest_attempt_started_at", BigInteger, nullable=True),
            Column("latest_attempt_completed_at", BigInteger, nullable=True),
            Column("latest_attempt_status", String, nullable=True),
            Column("latest_success_started_at", BigInteger, nullable=True),
            Column("latest_success_completed_at", BigInteger, nullable=True),
            Column("latest_success_checkpoint_payload", Text, nullable=True),
            Column("source_watermark_payload", Text, nullable=True),
            Column("latest_failed_at", BigInteger, nullable=True),
            Column("latest_error_message", Text, nullable=True),
        )
    if not _column_exists("ctx_session", "source_fingerprint"):
        op.add_column("ctx_session", Column("source_fingerprint", Text, nullable=False, server_default=""))
    if not _column_exists("ctx_event", "source_fingerprint"):
        op.add_column("ctx_event", Column("source_fingerprint", Text, nullable=False, server_default=""))

    source_columns = set(_columns("ctx_source"))
    if "imported_at" in source_columns or "checkpoint_payload" in source_columns:
        bind.execute(
            text(
                """
                CREATE TEMP TABLE temp_ctx_refresh_state_migration AS
                SELECT id AS source_id,
                       imported_at,
                       checkpoint_payload
                FROM ctx_source
                WHERE imported_at IS NOT NULL
                """
            )
        )
    if "imported_at" in source_columns:
        with op.batch_alter_table("ctx_source") as batch_op:
            batch_op.drop_column("imported_at")
    if "checkpoint_payload" in source_columns:
        with op.batch_alter_table("ctx_source") as batch_op:
            batch_op.drop_column("checkpoint_payload")
    if "imported_at" in source_columns or "checkpoint_payload" in source_columns:
        bind.execute(
            text(
                """
                INSERT OR REPLACE INTO ctx_refresh_state(
                    source_id,
                    latest_attempt_started_at,
                    latest_attempt_completed_at,
                    latest_attempt_status,
                    latest_success_started_at,
                    latest_success_completed_at,
                    latest_success_checkpoint_payload
                )
                SELECT source_id,
                       imported_at,
                       imported_at,
                       'success',
                       imported_at,
                       imported_at,
                       checkpoint_payload
                FROM temp_ctx_refresh_state_migration
                """
            )
        )
        bind.execute(text("DROP TABLE temp_ctx_refresh_state_migration"))
    _create_stable_views()


def downgrade() -> None:
    _drop_stable_views()
    if not _column_exists("ctx_source", "imported_at"):
        op.add_column("ctx_source", Column("imported_at", BigInteger, nullable=False, server_default="0"))
    if not _column_exists("ctx_source", "checkpoint_payload"):
        op.add_column("ctx_source", Column("checkpoint_payload", Text, nullable=True))
    if _table_exists("ctx_refresh_state"):
        op.get_bind().execute(
            text(
                """
                UPDATE ctx_source
                SET imported_at = coalesce((
                        SELECT latest_success_completed_at
                        FROM ctx_refresh_state
                        WHERE ctx_refresh_state.source_id = ctx_source.id
                    ), 0),
                    checkpoint_payload = (
                        SELECT latest_success_checkpoint_payload
                        FROM ctx_refresh_state
                        WHERE ctx_refresh_state.source_id = ctx_source.id
                    )
                """
            )
        )
        op.drop_table("ctx_refresh_state")
    if _column_exists("ctx_event", "source_fingerprint"):
        with op.batch_alter_table("ctx_event") as batch_op:
            batch_op.drop_column("source_fingerprint")
    if _column_exists("ctx_session", "source_fingerprint"):
        with op.batch_alter_table("ctx_session") as batch_op:
            batch_op.drop_column("source_fingerprint")
    _create_stable_views()


def _drop_stable_views() -> None:
    for view in reversed(default_ctx_sql_config().stable_views):
        op.execute(f"DROP VIEW IF EXISTS {view.name}")


def _create_stable_views() -> None:
    for statement in stable_view_create_statements(default_ctx_sql_config()):
        op.execute(statement)


def _table_exists(table_name: str) -> bool:
    return (
        op.get_bind()
        .execute(text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :name"), {"name": table_name})
        .scalar_one_or_none()
        is not None
    )


def _column_exists(table_name: str, column_name: str) -> bool:
    return column_name in _columns(table_name)


def _columns(table_name: str) -> tuple[str, ...]:
    rows = op.get_bind().execute(text(f"PRAGMA table_info({_quote_identifier(table_name)})")).mappings()
    return tuple(str(row["name"]) for row in rows)


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'
