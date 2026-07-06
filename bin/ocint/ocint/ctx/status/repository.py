from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ocint.ctx.db.schema import ctx_event, ctx_session, ctx_source, metadata
from ocint.ctx.models import CtxSource, CtxStatus
from ocint.ctx.sql.models import CtxSqlConfig


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

    def index_ready(self, config: CtxSqlConfig) -> bool:
        required_tables = set(metadata.tables) | {"alembic_version", "ctx_event_fts"}
        required_views = {view.name for view in config.stable_views}
        tables, views = self._sqlite_objects()

        return required_tables.issubset(tables) and required_views.issubset(views)

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
