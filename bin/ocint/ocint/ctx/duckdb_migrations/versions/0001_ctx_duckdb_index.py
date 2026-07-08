"""create duckdb ctx import index

Revision ID: 0001_ctx_duckdb_index
Revises:
Create Date: 2026-07-04
"""

from collections.abc import Sequence

from alembic import op

from ocint.ctx.duckdb_schema import metadata

revision = "0001_ctx_duckdb_index"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata.create_all(op.get_bind())
    _create_stable_views()


def downgrade() -> None:
    for view in ["ctx_sources", "ctx_files_touched", "ctx_events", "ctx_sessions"]:
        op.execute(f"DROP VIEW IF EXISTS {view}")
    metadata.drop_all(op.get_bind())


def _create_stable_views() -> None:
    for statement in _view_statements():
        op.execute(statement)


def _view_statements() -> Sequence[str]:
    return [
        """
        CREATE VIEW ctx_sessions AS
        SELECT provider,
               provider_session_id,
               session_id,
               parent_id,
               title,
               workspace,
               time_created,
               time_updated
        FROM ctx_session
        """,
        """
        CREATE VIEW ctx_events AS
        SELECT provider,
               provider_session_id,
               event_id,
               source_table,
               event_type,
               time_created,
               full_text AS text,
               source_path,
               citation
        FROM ctx_event
        """,
        """
        CREATE VIEW ctx_files_touched AS
        SELECT provider,
               path,
               provider_session_id,
               event_id,
               source_table
        FROM ctx_file_touched
        """,
        """
        CREATE VIEW ctx_sources AS
        SELECT provider,
               source_type,
               name,
               source_path AS path,
               sessions,
               events,
               imported_at
        FROM ctx_source
        """,
    ]
