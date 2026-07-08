import re
import time
from collections.abc import Iterable, Mapping
from typing import Any, override

from sqlalchemy import delete, func, insert, select, text, update

from ocint.ctx.duckdb_schema import ctx_event, ctx_file_touched, ctx_session, ctx_source
from ocint.ctx.models import CtxImportBatch, CtxImportWriteResult
from ocint.ctx.repository import (
    _CtxLocateReadRepository,
    _CtxRepositoryBase,
    _CtxSearchReadRepository,
    _CtxShowReadRepository,
    _CtxSqlProjectionRepository,
    _CtxStatusReadRepository,
    _FtsClause,
)


class _DuckDBCtxRepositoryBase(_CtxRepositoryBase):
    def _ensure_fts_extension(self) -> None:
        try:
            self._session.execute(text("LOAD fts"))
        except Exception:
            # A failed LOAD marks the current SQLAlchemy transaction as failed;
            # rollback is safe here because callers invoke this before writes.
            self._session.rollback()
            self._session.execute(text("INSTALL fts"))
            self._session.execute(text("LOAD fts"))


class DuckDBCtxImportRepository(_DuckDBCtxRepositoryBase):
    def replace_source_projection(self, batch: CtxImportBatch) -> CtxImportWriteResult:
        """Replace one source using explicit DuckDB IDs, then rebuild the static FTS index."""
        self._ensure_fts_extension()
        write_start = time.perf_counter()
        source_id = self._upsert_source(batch)
        self._clear_source_rows(source_id)
        session_rows = _assign_ids(
            (_with_source_id(row, source_id) for row in batch.session_rows),
            start=self._next_id(ctx_session),
        )
        event_rows = _assign_ids(
            (_with_event_key(_with_source_id(row, source_id), source_id) for row in batch.event_rows),
            start=self._next_id(ctx_event),
        )
        file_rows = _assign_ids(
            (_with_source_id(row, source_id) for row in batch.file_rows),
            start=self._next_id(ctx_file_touched),
        )
        if session_rows:
            self._session.execute(insert(ctx_session), session_rows)
        if event_rows:
            self._session.execute(insert(ctx_event), event_rows)
        if file_rows:
            self._session.execute(insert(ctx_file_touched), file_rows)
        write_ms = _elapsed_ms(write_start)
        fts_start = time.perf_counter()
        self._rebuild_fts_index()
        fts_ms = _elapsed_ms(fts_start)
        return CtxImportWriteResult(
            source_id=source_id,
            sessions_written=len(session_rows),
            events_written=len(event_rows),
            files_written=len(file_rows),
            write_ms=write_ms,
            fts_ms=fts_ms,
        )

    def _upsert_source(self, batch: CtxImportBatch) -> int:
        existing_id = self._session.execute(
            select(ctx_source.c.id).where(
                ctx_source.c.provider == batch.source.provider,
                ctx_source.c.source_type == batch.source.source_type,
                ctx_source.c.source_path == batch.source.source_path,
            )
        ).scalar_one_or_none()
        values = batch.source.model_dump()
        if existing_id is not None:
            self._session.execute(update(ctx_source).where(ctx_source.c.id == existing_id).values(values))
            return int(existing_id)
        source_id = self._next_id(ctx_source)
        self._session.execute(insert(ctx_source), [{"id": source_id, **values}])
        return source_id

    def _clear_source_rows(self, source_id: int) -> None:
        self._session.execute(delete(ctx_file_touched).where(ctx_file_touched.c.source_id == source_id))
        self._session.execute(delete(ctx_event).where(ctx_event.c.source_id == source_id))
        self._session.execute(delete(ctx_session).where(ctx_session.c.source_id == source_id))

    def _next_id(self, table: Any) -> int:
        return int(self._session.execute(select(func.coalesce(func.max(table.c.id), 0) + 1)).scalar_one() or 1)

    def _rebuild_fts_index(self) -> None:
        # DuckDB FTS is a static auxiliary index; unlike SQLite FTS5 it must be
        # rebuilt after the ctx_event table is replaced.
        self._session.execute(
            text(
                "PRAGMA create_fts_index("
                "'ctx_event', 'event_key', 'search_text', "
                "stemmer='none', stopwords='none', overwrite=1)"
            )
        )


class _DuckDBFtsMixin(_DuckDBCtxRepositoryBase):
    def _fts_clause(self, query: str, params: dict[str, Any]) -> _FtsClause:
        fts_query = _fts_query(query)
        if not fts_query:
            return _FtsClause()
        self._ensure_fts_extension()
        params["fts_query"] = fts_query
        return _FtsClause(where_sql="fts_main_ctx_event.match_bm25(e.event_key, :fts_query) IS NOT NULL")


class DuckDBCtxSearchRepository(_DuckDBFtsMixin, _CtxSearchReadRepository):
    pass


class DuckDBCtxShowRepository(_CtxShowReadRepository, _DuckDBCtxRepositoryBase):
    pass


class DuckDBCtxLocateRepository(_CtxLocateReadRepository, _DuckDBCtxRepositoryBase):
    pass


class DuckDBCtxStatusRepository(_CtxStatusReadRepository, _DuckDBCtxRepositoryBase):
    @override
    def index_ready(self) -> bool:
        required = {
            "alembic_version",
            "ctx_source",
            "ctx_session",
            "ctx_event",
            "ctx_file_touched",
            "ctx_sessions",
            "ctx_events",
            "ctx_files_touched",
            "ctx_sources",
        }
        rows = self._session.execute(
            text(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name IN ('alembic_version', 'ctx_source', 'ctx_session', 'ctx_event', 'ctx_file_touched', 'ctx_sessions', 'ctx_events', 'ctx_files_touched', 'ctx_sources')
                """
            )
        ).scalars()
        return set(rows) == required


class DuckDBCtxSqlRepository(_CtxSqlProjectionRepository, _DuckDBCtxRepositoryBase):
    pass


def _fts_query(query: str) -> str | None:
    terms = re.findall(r"[\w]+", query.lower())
    if not terms:
        return None
    return " ".join(terms)


def _assign_ids(rows: Iterable[Mapping[str, object]], *, start: int) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for offset, row in enumerate(rows):
        result.append({"id": start + offset, **dict(row)})
    return result


def _with_source_id(row: Mapping[str, object], source_id: int) -> dict[str, object]:
    values = dict(row)
    values["source_id"] = source_id
    return values


def _with_event_key(row: Mapping[str, object], source_id: int) -> dict[str, object]:
    values = dict(row)
    values["event_key"] = f"{source_id}:{values['source_table']}:{values['event_id']}"
    return values


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000
