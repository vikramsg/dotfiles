"""create ctx import index

Revision ID: 20260704_create_ctx_index
Revises:
Create Date: 2026-07-04
"""

from alembic import op

from ocint.ctx.db.schema import ctx_event_fts_create_statement, ctx_event_fts_name, metadata
from ocint.ctx.sql.models import default_ctx_sql_config, stable_view_create_statements

revision = "20260704_create_ctx_index"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata.create_all(bind)
    # FTS is maintained explicitly by the import workflow so read commands never
    # need triggers or writes against either the ctx DB or the OpenCode source.
    op.execute(ctx_event_fts_create_statement())
    for statement in stable_view_create_statements(default_ctx_sql_config()):
        op.execute(statement)


def downgrade() -> None:
    for view in reversed(default_ctx_sql_config().stable_views):
        op.execute(f"DROP VIEW IF EXISTS {view.name}")
    op.execute(f"DROP TABLE IF EXISTS {ctx_event_fts_name()}")
    metadata.drop_all(op.get_bind())
