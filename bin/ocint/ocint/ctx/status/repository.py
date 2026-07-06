from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ocint.ctx.models import CtxSource, CtxStatus
from ocint.ctx.schema import ctx_event, ctx_session, ctx_source


class CtxStatusRepository:
    def __init__(self, session: Session, *, db_path: Path) -> None:
        self._session = session
        self.db_path = db_path

    def status(self) -> CtxStatus:
        index_ready = self.index_ready()
        if not index_ready:
            return CtxStatus(
                db_path=self.db_path,
                db_exists=self.db_path.exists(),
            )
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
        if not self.index_ready():
            return []
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

    def index_ready(self) -> bool:
        required = {
            "alembic_version",
            "ctx_event_fts",
            "ctx_sessions",
            "ctx_events",
            "ctx_files_touched",
            "ctx_sources",
        }
        rows = self._session.execute(
            text(
                """
                SELECT name FROM sqlite_master
                WHERE name IN ('alembic_version', 'ctx_event_fts', 'ctx_sessions', 'ctx_events', 'ctx_files_touched', 'ctx_sources')
                """
            )
        ).scalars()
        return set(rows) == required
