import re
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, override

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ocint.ctx.models import CtxImportBatch, CtxImportWriteResult, CtxSearchCandidate, CtxSource, CtxStatus
from ocint.ctx.schema import (
    STABLE_CTX_VIEW_COLUMNS,
    ctx_event,
    ctx_file_touched,
    ctx_session,
    ctx_source,
)


class _CtxRepositoryBase:
    def __init__(self, session: Session, *, db_path: Path) -> None:
        self._session = session
        self.db_path = db_path


@dataclass(frozen=True)
class _FtsClause:
    join_sql: str = ""
    where_sql: str = ""


class CtxImportRepository(_CtxRepositoryBase):
    def replace_source_projection(self, batch: CtxImportBatch) -> CtxImportWriteResult:
        """Replace one OpenCode source projection with batched SQLite writes and FTS rows."""
        write_start = time.perf_counter()
        source_id = self._upsert_source(batch)
        self._clear_source_rows(source_id)
        session_rows = [_with_source_id(row, source_id) for row in batch.session_rows]
        event_rows = [_with_source_id(row, source_id) for row in batch.event_rows]
        file_rows = [_with_source_id(row, source_id) for row in batch.file_rows]
        if session_rows:
            self._session.execute(insert(ctx_session), session_rows)
        if event_rows:
            self._session.execute(insert(ctx_event), event_rows)
        event_pk_by_key = self._event_pk_by_key(source_id)
        fts_rows = [
            {
                "search_text": row["search_text"],
                "event_pk": event_pk_by_key[(str(row["source_table"]), str(row["event_id"]))],
                "event_id": row["event_id"],
                "source_table": row["source_table"],
            }
            for row in event_rows
        ]
        if file_rows:
            self._session.execute(insert(ctx_file_touched), file_rows)
        write_ms = _elapsed_ms(write_start)
        fts_start = time.perf_counter()
        if fts_rows:
            self._session.execute(
                text(
                    """
                    INSERT INTO ctx_event_fts(search_text, event_pk, event_id, source_table)
                    VALUES (:search_text, :event_pk, :event_id, :source_table)
                    """
                ),
                fts_rows,
            )
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
        values = batch.source.model_dump()
        statement = sqlite_insert(ctx_source).values(values)
        self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[ctx_source.c.provider, ctx_source.c.source_type, ctx_source.c.source_path],
                set_=values,
            )
        )
        source_id = self._session.execute(
            select(ctx_source.c.id).where(
                ctx_source.c.provider == batch.source.provider,
                ctx_source.c.source_type == batch.source.source_type,
                ctx_source.c.source_path == batch.source.source_path,
            )
        ).scalar_one()
        return int(source_id)

    def _clear_source_rows(self, source_id: int) -> None:
        self._session.execute(
            text("DELETE FROM ctx_event_fts WHERE event_pk IN (SELECT id FROM ctx_event WHERE source_id = :source_id)"),
            {"source_id": source_id},
        )
        self._session.execute(delete(ctx_file_touched).where(ctx_file_touched.c.source_id == source_id))
        self._session.execute(delete(ctx_event).where(ctx_event.c.source_id == source_id))
        self._session.execute(delete(ctx_session).where(ctx_session.c.source_id == source_id))

    def _event_pk_by_key(self, source_id: int) -> dict[tuple[str, str], int]:
        rows = self._session.execute(
            select(ctx_event.c.source_table, ctx_event.c.event_id, ctx_event.c.id).where(
                ctx_event.c.source_id == source_id
            )
        )
        return {(str(row.source_table), str(row.event_id)): int(row.id) for row in rows}


class _SQLiteFtsMixin:
    def _fts_clause(self, query: str, params: dict[str, Any]) -> _FtsClause:
        fts_query = _sqlite_fts_query(query)
        if not fts_query:
            return _FtsClause()
        params["fts_query"] = fts_query
        return _FtsClause(
            join_sql="JOIN ctx_event_fts ON CAST(ctx_event_fts.event_pk AS INTEGER) = e.id",
            where_sql="ctx_event_fts MATCH :fts_query",
        )


class _CtxSearchReadRepository(_CtxRepositoryBase):
    def search_events(
        self,
        *,
        query: str,
        query_tokens: list[str],
        required_terms: list[str],
        since_ms: int | None,
        session_id: str | None,
        workspace: str | None,
        file_filter: str | None,
        include_subagents: bool,
        limit: int | None,
    ) -> list[CtxSearchCandidate]:
        """Return already-filtered rows; required predicates are applied before LIMIT."""
        params: dict[str, Any] = {}
        where = ["1 = 1"]
        fts = self._fts_clause(query, params)
        if fts.where_sql:
            where.append(fts.where_sql)
        _add_search_text_filters(where, params, query_tokens, prefix="query_token")
        _add_search_text_filters(where, params, required_terms, prefix="required_term")
        if since_ms is not None:
            where.append("e.time_created IS NOT NULL AND e.time_created >= :since_ms")
            params["since_ms"] = since_ms
        if session_id:
            where.append("e.provider_session_id = :session_id")
            params["session_id"] = session_id
        if workspace:
            where.append(
                "lower(coalesce(s.workspace, '') || ' ' || coalesce(s.title, '')) LIKE :workspace_filter ESCAPE '\\'"
            )
            params["workspace_filter"] = _like_pattern(workspace.lower())
        if file_filter:
            where.append(
                "EXISTS ("
                "SELECT 1 FROM ctx_file_touched ft "
                "WHERE ft.source_id = e.source_id "
                "AND ft.source_table = e.source_table "
                "AND ft.event_id = e.event_id "
                "AND lower(ft.path) LIKE :file_filter ESCAPE '\\')"
            )
            params["file_filter"] = _like_pattern(file_filter.lower())
        if not include_subagents:
            where.append("s.parent_id IS NULL")
        limit_sql = ""
        if limit is not None:
            limit_sql = "LIMIT :limit"
            params["limit"] = limit
        statement = text(
            f"""
            {_candidate_columns()}
            FROM ctx_event AS e
            LEFT JOIN ctx_session AS s
              ON s.source_id = e.source_id
             AND s.provider_session_id = e.provider_session_id
            JOIN ctx_source AS src ON src.id = e.source_id
            {fts.join_sql}
            WHERE {" AND ".join(where)}
            ORDER BY coalesce(e.time_created, 0) DESC, e.source_table DESC, e.event_id DESC
            {limit_sql}
            """
        )
        return [CtxSearchCandidate.model_validate(row) for row in self._session.execute(statement, params).mappings()]

    def _fts_clause(self, query: str, params: dict[str, Any]) -> _FtsClause:
        _ = query, params
        raise NotImplementedError


class _CtxLookupReadRepository(_CtxRepositoryBase):
    def find_event(self, event_id: str) -> CtxSearchCandidate | None:
        candidates = _candidate_query(self._session, "e.event_id = :event_id", {"event_id": event_id}, limit=1)
        return candidates[0] if candidates else None

    def find_session(self, session_id: str) -> Mapping[str, Any] | None:
        return _find_session(self._session, session_id)


class _CtxShowReadRepository(_CtxLookupReadRepository):
    def session_events(self, *, source_id: int, session_id: str) -> list[CtxSearchCandidate]:
        return _candidate_query(
            self._session,
            "e.source_id = :source_id AND e.provider_session_id = :session_id",
            {"source_id": source_id, "session_id": session_id},
            limit=None,
            ascending=True,
        )

    def event_window(self, selected: CtxSearchCandidate, *, window: int) -> list[CtxSearchCandidate]:
        events = self.session_events(source_id=selected.source_id, session_id=selected.session_id)
        index = next((i for i, event in enumerate(events) if event.event_id == selected.event_id), 0)
        start = max(0, index - window)
        end = min(len(events), index + window + 1)
        return events[start:end]


class _CtxLocateReadRepository(_CtxLookupReadRepository):
    pass


class _CtxStatusReadRepository(_CtxRepositoryBase):
    def status(self, *, source_db_path: Path | None = None) -> CtxStatus:
        index_ready = self.index_ready()
        if not index_ready:
            return CtxStatus(
                db_path=self.db_path,
                db_exists=self.db_path.exists(),
                source_db_path=source_db_path,
                source_db_exists=source_db_path.exists() if source_db_path is not None else False,
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
            source_db_path=source_db_path,
            source_db_exists=source_db_path.exists() if source_db_path is not None else False,
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
        raise NotImplementedError


class _CtxSqlProjectionRepository(_CtxRepositoryBase):
    def load_stable_projection_rows(self) -> dict[str, list[dict[str, Any]]]:
        return {name: self._load_projection_rows(name, columns) for name, columns in STABLE_CTX_VIEW_COLUMNS.items()}

    def _load_projection_rows(self, name: str, columns: tuple[str, ...]) -> list[dict[str, Any]]:
        column_sql = ", ".join(_quote_identifier(column) for column in columns)
        rows = self._session.execute(text(f"SELECT {column_sql} FROM {_quote_identifier(name)}")).mappings()
        return [dict(row) for row in rows]


class CtxSearchRepository(_SQLiteFtsMixin, _CtxSearchReadRepository):
    pass


class CtxShowRepository(_CtxShowReadRepository):
    pass


class CtxLocateRepository(_CtxLocateReadRepository):
    pass


class CtxStatusRepository(_CtxStatusReadRepository):
    @override
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


class CtxSqlRepository(_CtxSqlProjectionRepository):
    pass


def _with_source_id(row: Mapping[str, object], source_id: int) -> dict[str, object]:
    values = dict(row)
    values["source_id"] = source_id
    return values


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def _find_session(session: Session, session_id: str) -> Mapping[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                SELECT s.id AS session_pk,
                       s.source_id AS source_id,
                       s.provider AS provider,
                       s.provider_session_id AS session_id,
                       s.parent_id AS parent_id,
                       s.title AS title,
                       s.workspace AS workspace,
                       s.time_created AS time_created,
                       s.time_updated AS time_updated,
                       src.source_path AS source_db_path,
                       (
                           SELECT count(*)
                           FROM ctx_event AS e
                           WHERE e.source_id = s.source_id
                             AND e.provider_session_id = s.provider_session_id
                       ) AS event_count
                FROM ctx_session AS s
                JOIN ctx_source AS src ON src.id = s.source_id
                WHERE s.provider_session_id = :session_id
                ORDER BY src.imported_at DESC, s.id DESC
                LIMIT 1
                """
            ),
            {"session_id": session_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


def _candidate_query(
    session: Session,
    predicate: str,
    params: Mapping[str, Any],
    *,
    limit: int | None,
    ascending: bool = False,
) -> list[CtxSearchCandidate]:
    order_direction = "ASC" if ascending else "DESC"
    limit_sql = "" if limit is None else "LIMIT :limit"
    effective_params = dict(params)
    if limit is not None:
        effective_params["limit"] = limit
    rows = session.execute(
        text(
            f"""
            {_candidate_columns()}
            FROM ctx_event AS e
            LEFT JOIN ctx_session AS s
              ON s.source_id = e.source_id
             AND s.provider_session_id = e.provider_session_id
            JOIN ctx_source AS src ON src.id = e.source_id
            WHERE {predicate}
            ORDER BY coalesce(e.time_created, 0) {order_direction}, e.source_table {order_direction}, e.event_id {order_direction}
            {limit_sql}
            """
        ),
        effective_params,
    ).mappings()
    return [CtxSearchCandidate.model_validate(row) for row in rows]


def _candidate_columns() -> str:
    return """
            SELECT e.id AS event_pk,
                   e.source_id AS source_id,
                   e.provider AS provider,
                   coalesce(e.provider_session_id, '') AS session_id,
                   s.parent_id AS parent_id,
                   e.event_id AS event_id,
                   e.source_table AS source_table,
                   e.message_id AS message_id,
                   e.event_type AS event_type,
                   e.time_created AS time_created,
                   e.time_updated AS time_updated,
                   s.title AS title,
                   s.workspace AS workspace,
                   e.source_path AS source_path,
                   e.full_text AS full_text,
                   e.search_text AS search_text,
                   e.citation AS citation,
                   src.source_path AS source_db_path
    """


def _add_search_text_filters(where: list[str], params: dict[str, Any], values: Iterable[str], *, prefix: str) -> None:
    for index, value in enumerate(_unique_non_empty(values)):
        key = f"{prefix}_{index}"
        where.append(f"lower(e.search_text) LIKE :{key} ESCAPE '\\'")
        params[key] = _like_pattern(value.lower())


def _unique_non_empty(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _sqlite_fts_query(query: str) -> str | None:
    terms = re.findall(r"[\w]+", query.lower())
    if not terms:
        return None
    return " ".join(f'"{term}"' for term in terms)


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'
