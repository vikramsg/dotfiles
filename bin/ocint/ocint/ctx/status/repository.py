from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ocint.ctx.db.schema import (
    ctx_event,
    ctx_event_fts_columns,
    ctx_event_fts_create_statement,
    ctx_event_fts_name,
    ctx_session,
    ctx_source,
    metadata,
)
from ocint.ctx.models import CtxSource, CtxStatus
from ocint.ctx.sql.models import CtxSqlConfig, CtxSqlStableView, stable_view_create_statement


class CtxStatusRepository:
    def __init__(self, session: Session, *, db_path: Path) -> None:
        self._session = session
        self.db_path = db_path

    def status(self) -> CtxStatus:
        sessions = int(self._session.execute(select(func.count()).select_from(ctx_session)).scalar_one() or 0)
        primary_sessions = int(
            self._session.execute(
                select(func.count()).select_from(ctx_session).where(ctx_session.c.parent_id.is_(None))
            ).scalar_one()
            or 0
        )
        events = int(self._session.execute(select(func.count()).select_from(ctx_event)).scalar_one() or 0)
        sources = int(self._session.execute(select(func.count()).select_from(ctx_source)).scalar_one() or 0)
        return CtxStatus(
            db_path=self.db_path,
            db_exists=True,
            index_ready=True,
            sessions=sessions,
            primary_sessions=primary_sessions,
            events=events,
            sources=sources,
        )

    def sources(self) -> list[CtxSource]:
        statement = select(
            ctx_source.c.provider,
            ctx_source.c.source_type,
            ctx_source.c.name,
            ctx_source.c.source_path.label("path"),
            ctx_source.c.events.label("count"),
            ctx_source.c.sessions,
            ctx_source.c.events,
            ctx_source.c.imported_at,
        ).order_by(ctx_source.c.provider, ctx_source.c.name, ctx_source.c.source_path)
        return [CtxSource.model_validate(row) for row in self._session.execute(statement).mappings()]

    def index_ready(self, config: CtxSqlConfig, expected_revision: str) -> bool:
        """Return True only when the DB matches the migration and public SQL contracts."""
        try:
            return (
                self._has_required_objects(config)
                and self._has_exact_alembic_revision(expected_revision)
                and self._has_required_physical_columns()
                and self._has_expected_fts_columns()
                and self._has_expected_stable_views(config)
            )
        except SQLAlchemyError:
            return False

    def _has_required_objects(self, config: CtxSqlConfig) -> bool:
        required_tables = set(metadata.tables) | {"alembic_version", ctx_event_fts_name()}
        required_views = {view.name for view in config.stable_views}
        tables, views = self._sqlite_objects()

        return required_tables.issubset(tables) and required_views.issubset(views)

    def _has_exact_alembic_revision(self, expected_revision: str) -> bool:
        rows = self._session.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        return rows == [expected_revision]

    def _has_required_physical_columns(self) -> bool:
        for table in metadata.sorted_tables:
            actual_columns = set(self._sqlite_columns(table.name))
            expected_columns = {column.name for column in table.columns}
            if not expected_columns.issubset(actual_columns):
                return False
        return True

    def _has_expected_fts_columns(self) -> bool:
        if self._sqlite_columns(ctx_event_fts_name()) != ctx_event_fts_columns():
            return False
        # SQLite records FTS5 virtual tables as sqlite_master type='table'; the
        # canonical CREATE statement distinguishes them from same-column tables.
        actual_sql = self._sqlite_table_sql(ctx_event_fts_name())
        if actual_sql is None:
            return False
        return _normalize_schema_sql(actual_sql) == _normalize_schema_sql(ctx_event_fts_create_statement())

    def _has_expected_stable_views(self, config: CtxSqlConfig) -> bool:
        return all(self._stable_view_matches_contract(view) for view in config.stable_views)

    def _stable_view_matches_contract(self, view: CtxSqlStableView) -> bool:
        expected_columns = tuple(column.name for column in view.columns)
        if self._sqlite_columns(view.name) != expected_columns:
            return False
        actual_sql = self._sqlite_view_sql(view.name)
        if actual_sql is None:
            return False
        return _normalize_schema_sql(actual_sql) == _normalize_schema_sql(stable_view_create_statement(view))

    def _sqlite_objects(self) -> tuple[set[str], set[str]]:
        rows = self._session.execute(text("SELECT name, type FROM sqlite_master")).mappings()
        tables: set[str] = set()
        views: set[str] = set()
        for row in rows:
            name = str(row["name"])
            match row["type"]:
                case "table":
                    tables.add(name)
                case "view":
                    views.add(name)
        return tables, views

    def _sqlite_columns(self, object_name: str) -> tuple[str, ...]:
        rows = self._session.execute(text(f"PRAGMA table_info({_quote_identifier(object_name)})")).mappings()
        return tuple(str(row["name"]) for row in rows)

    def _sqlite_view_sql(self, view_name: str) -> str | None:
        return self._session.execute(
            text("SELECT sql FROM sqlite_master WHERE type = 'view' AND name = :name"), {"name": view_name}
        ).scalar_one_or_none()

    def _sqlite_table_sql(self, table_name: str) -> str | None:
        return self._session.execute(
            text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = :name"), {"name": table_name}
        ).scalar_one_or_none()


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def _normalize_schema_sql(sql: str) -> str:
    return " ".join(sql.rstrip(";").split())
