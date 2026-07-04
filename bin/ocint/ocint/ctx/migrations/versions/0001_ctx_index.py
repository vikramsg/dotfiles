"""create ctx import index

Revision ID: 0001_ctx_index
Revises:
Create Date: 2026-07-04
"""

from collections.abc import Sequence

from alembic import op

from ocint.ctx.schema import metadata

revision = "0001_ctx_index"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata.create_all(bind)
    # FTS is maintained explicitly by the import workflow so read commands never
    # need triggers or writes against either the ctx DB or the OpenCode source.
    op.execute(
        "CREATE VIRTUAL TABLE ctx_event_fts USING fts5("
        "search_text, event_pk UNINDEXED, event_id UNINDEXED, source_table UNINDEXED)"
    )
    _create_stable_views()


def downgrade() -> None:
    for view in ["ctx_sources", "ctx_files_touched", "ctx_events", "ctx_sessions"]:
        op.execute(f"DROP VIEW IF EXISTS {view}")
    op.execute("DROP TABLE IF EXISTS ctx_event_fts")
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
