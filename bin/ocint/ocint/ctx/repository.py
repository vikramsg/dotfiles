import re
import sqlite3
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import bindparam, delete, func, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ocint._sqlsafe import normalize_select_sql
from ocint.ctx.models import CtxSearchCandidate, CtxSource, CtxStatus
from ocint.ctx.schema import (
    STABLE_CTX_VIEW_COLUMNS,
    STABLE_CTX_VIEWS,
    ctx_event,
    ctx_file_touched,
    ctx_session,
    ctx_source,
)

Authorizer = Callable[[int, str | None, str | None, str | None, str | None], int]

_ALLOWED_SANDBOX_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
}
if hasattr(sqlite3, "SQLITE_RECURSIVE"):
    _ALLOWED_SANDBOX_ACTIONS.add(sqlite3.SQLITE_RECURSIVE)

_SANDBOX_INTEGER_COLUMNS = {"time_created", "time_updated", "sessions", "events", "imported_at"}


class _CtxRepositoryBase:
    def __init__(self, session: Session, *, db_path: Path) -> None:
        self._session = session
        self.db_path = db_path


class CtxImportRepository(_CtxRepositoryBase):
    def upsert_source(
        self,
        *,
        provider: str,
        source_type: str,
        name: str,
        source_path: str,
        imported_at: int,
        sessions: int,
        events: int,
        checkpoint_payload: str | None,
    ) -> int:
        values = {
            "provider": provider,
            "source_type": source_type,
            "name": name,
            "source_path": source_path,
            "imported_at": imported_at,
            "sessions": sessions,
            "events": events,
            "checkpoint_payload": checkpoint_payload,
        }
        statement = sqlite_insert(ctx_source).values(values)
        self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[ctx_source.c.provider, ctx_source.c.source_type, ctx_source.c.source_path],
                set_=values,
            )
        )
        source_id = self._session.execute(
            select(ctx_source.c.id).where(
                ctx_source.c.provider == provider,
                ctx_source.c.source_type == source_type,
                ctx_source.c.source_path == source_path,
            )
        ).scalar_one()
        return int(source_id)

    def clear_source_rows(self, source_id: int) -> None:
        event_pks = list(
            self._session.execute(select(ctx_event.c.id).where(ctx_event.c.source_id == source_id)).scalars().all()
        )
        if event_pks:
            self._session.execute(
                text("DELETE FROM ctx_event_fts WHERE event_pk IN :event_pks").bindparams(
                    bindparam("event_pks", expanding=True)
                ),
                {"event_pks": event_pks},
            )
        self._session.execute(delete(ctx_file_touched).where(ctx_file_touched.c.source_id == source_id))
        self._session.execute(delete(ctx_event).where(ctx_event.c.source_id == source_id))
        self._session.execute(delete(ctx_session).where(ctx_session.c.source_id == source_id))

    def upsert_sessions(self, sessions: Iterable[Mapping[str, Any]]) -> int:
        count = 0
        for values in sessions:
            statement = sqlite_insert(ctx_session).values(dict(values))
            excluded = statement.excluded
            self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=[ctx_session.c.source_id, ctx_session.c.provider_session_id],
                    set_={
                        "provider": excluded.provider,
                        "session_id": excluded.session_id,
                        "parent_id": excluded.parent_id,
                        "title": excluded.title,
                        "workspace": excluded.workspace,
                        "time_created": excluded.time_created,
                        "time_updated": excluded.time_updated,
                        "source_path": excluded.source_path,
                        "payload_json": excluded.payload_json,
                    },
                )
            )
            count += 1
        return count

    def upsert_event_with_files(self, event_values: Mapping[str, Any], paths: Iterable[str]) -> int:
        values = dict(event_values)
        statement = sqlite_insert(ctx_event).values(values)
        excluded = statement.excluded
        self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[ctx_event.c.source_id, ctx_event.c.source_table, ctx_event.c.event_id],
                set_={
                    "provider": excluded.provider,
                    "provider_session_id": excluded.provider_session_id,
                    "message_id": excluded.message_id,
                    "event_type": excluded.event_type,
                    "time_created": excluded.time_created,
                    "time_updated": excluded.time_updated,
                    "source_path": excluded.source_path,
                    "full_text": excluded.full_text,
                    "search_text": excluded.search_text,
                    "payload_json": excluded.payload_json,
                    "citation": excluded.citation,
                },
            )
        )
        event_pk = int(
            self._session.execute(
                select(ctx_event.c.id).where(
                    ctx_event.c.source_id == values["source_id"],
                    ctx_event.c.source_table == values["source_table"],
                    ctx_event.c.event_id == values["event_id"],
                )
            ).scalar_one()
        )
        self._replace_event_fts(event_pk=event_pk, values=values)
        self._replace_files(values=values, paths=paths)
        return event_pk

    def _replace_event_fts(self, *, event_pk: int, values: Mapping[str, Any]) -> None:
        self._session.execute(text("DELETE FROM ctx_event_fts WHERE event_pk = :event_pk"), {"event_pk": event_pk})
        self._session.execute(
            text(
                """
                INSERT INTO ctx_event_fts(search_text, event_pk, event_id, source_table)
                VALUES (:search_text, :event_pk, :event_id, :source_table)
                """
            ),
            {
                "search_text": values["search_text"],
                "event_pk": event_pk,
                "event_id": values["event_id"],
                "source_table": values["source_table"],
            },
        )

    def _replace_files(self, *, values: Mapping[str, Any], paths: Iterable[str]) -> None:
        self._session.execute(
            delete(ctx_file_touched).where(
                ctx_file_touched.c.source_id == values["source_id"],
                ctx_file_touched.c.source_table == values["source_table"],
                ctx_file_touched.c.event_id == values["event_id"],
            )
        )
        seen: set[str] = set()
        for path in paths:
            if not path or path in seen:
                continue
            seen.add(path)
            statement = sqlite_insert(ctx_file_touched).values(
                {
                    "source_id": values["source_id"],
                    "provider": values["provider"],
                    "path": path,
                    "provider_session_id": values["provider_session_id"],
                    "event_id": values["event_id"],
                    "source_table": values["source_table"],
                }
            )
            self._session.execute(statement.on_conflict_do_nothing())


class CtxSearchRepository(_CtxRepositoryBase):
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
        join_fts = ""
        fts_query = _fts_query(query)
        if fts_query:
            join_fts = "JOIN ctx_event_fts ON CAST(ctx_event_fts.event_pk AS INTEGER) = e.id"
            where.append("ctx_event_fts MATCH :fts_query")
            params["fts_query"] = fts_query
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
            {join_fts}
            WHERE {" AND ".join(where)}
            ORDER BY coalesce(e.time_created, 0) DESC, e.source_table DESC, e.event_id DESC
            {limit_sql}
            """
        )
        return [CtxSearchCandidate.model_validate(row) for row in self._session.execute(statement, params).mappings()]


class CtxShowRepository(_CtxRepositoryBase):
    def find_event(self, event_id: str) -> CtxSearchCandidate | None:
        candidates = _candidate_query(self._session, "e.event_id = :event_id", {"event_id": event_id}, limit=1)
        return candidates[0] if candidates else None

    def find_session(self, session_id: str) -> Mapping[str, Any] | None:
        return _find_session(self._session, session_id)

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


class CtxLocateRepository(_CtxRepositoryBase):
    def find_event(self, event_id: str) -> CtxSearchCandidate | None:
        candidates = _candidate_query(self._session, "e.event_id = :event_id", {"event_id": event_id}, limit=1)
        return candidates[0] if candidates else None

    def find_session(self, session_id: str) -> Mapping[str, Any] | None:
        return _find_session(self._session, session_id)


class CtxStatusRepository(_CtxRepositoryBase):
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


class CtxSqlRepository(_CtxRepositoryBase):
    def execute_stable_view_query(self, sql: str) -> list[dict[str, Any]]:
        query = normalize_select_sql(sql)
        _reject_shadowed_ctx_views(query)
        rows_by_projection = self._load_stable_projection_rows()
        sandbox = _stable_projection_sandbox(rows_by_projection)
        try:
            sandbox.set_authorizer(_stable_projection_authorizer())
            rows = sandbox.execute(query).fetchall()
        finally:
            sandbox.set_authorizer(None)
            sandbox.close()
        return [dict(row) for row in rows]

    def _load_stable_projection_rows(self) -> dict[str, list[dict[str, Any]]]:
        return {name: self._load_projection_rows(name, columns) for name, columns in STABLE_CTX_VIEW_COLUMNS.items()}

    def _load_projection_rows(self, name: str, columns: tuple[str, ...]) -> list[dict[str, Any]]:
        column_sql = ", ".join(_quote_identifier(column) for column in columns)
        rows = self._session.execute(text(f"SELECT {column_sql} FROM {_quote_identifier(name)}")).mappings()
        return [dict(row) for row in rows]


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
                       count(e.id) AS event_count
                FROM ctx_session AS s
                JOIN ctx_source AS src ON src.id = s.source_id
                LEFT JOIN ctx_event AS e
                  ON e.source_id = s.source_id
                 AND e.provider_session_id = s.provider_session_id
                WHERE s.provider_session_id = :session_id
                GROUP BY s.id
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


def _fts_query(query: str) -> str | None:
    terms = re.findall(r"[\w]+", query.lower())
    if not terms:
        return None
    return " ".join(f'"{term}"' for term in terms)


def _stable_projection_sandbox(rows_by_projection: Mapping[str, Iterable[Mapping[str, Any]]]) -> sqlite3.Connection:
    """Build a transient SQL environment containing only public ctx projections."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        for name, columns in STABLE_CTX_VIEW_COLUMNS.items():
            _create_sandbox_table(connection, name, columns)
            _insert_sandbox_rows(connection, name, columns, rows_by_projection.get(name, []))
        # `query_only` protects the materialized sandbox even if a future SQL
        # normalizer bug lets a write-like statement reach sqlite3 execution.
        connection.execute("PRAGMA query_only = ON")
    except Exception:
        connection.close()
        raise
    return connection


def _create_sandbox_table(connection: sqlite3.Connection, name: str, columns: tuple[str, ...]) -> None:
    column_defs = ", ".join(f"{_quote_identifier(column)} {_sandbox_column_type(column)}" for column in columns)
    connection.execute(f"CREATE TABLE {_quote_identifier(name)} ({column_defs})")


def _insert_sandbox_rows(
    connection: sqlite3.Connection,
    name: str,
    columns: tuple[str, ...],
    rows: Iterable[Mapping[str, Any]],
) -> None:
    materialized_rows = [dict(row) for row in rows]
    if not materialized_rows:
        return
    column_sql = ", ".join(_quote_identifier(column) for column in columns)
    parameter_sql = ", ".join(f":{column}" for column in columns)
    connection.executemany(
        f"INSERT INTO {_quote_identifier(name)} ({column_sql}) VALUES ({parameter_sql})",
        materialized_rows,
    )


def _stable_projection_authorizer() -> Authorizer:
    """Allow reads only from materialized stable projection tables and columns."""
    allowed_columns = {name: frozenset(columns) for name, columns in STABLE_CTX_VIEW_COLUMNS.items()}

    def authorize(action: int, arg1: str | None, arg2: str | None, _db: str | None, _source: str | None) -> int:
        if action not in _ALLOWED_SANDBOX_ACTIONS:
            return sqlite3.SQLITE_DENY
        if action != sqlite3.SQLITE_READ:
            return sqlite3.SQLITE_OK

        table = _normalize_identifier(arg1)
        column = _normalize_identifier(arg2)
        if table not in allowed_columns:
            return sqlite3.SQLITE_DENY
        if column in {None, ""}:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_OK if column in allowed_columns[table] else sqlite3.SQLITE_DENY

    return authorize


def _sandbox_column_type(column: str) -> str:
    return "INTEGER" if column in _SANDBOX_INTEGER_COLUMNS else "TEXT"


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def _normalize_identifier(identifier: str | None) -> str | None:
    return identifier.lower() if identifier is not None else None


def _reject_shadowed_ctx_views(query: str) -> None:
    # A CTE named like an approved view can make SQLite's authorizer report
    # source=<ctx view name> for non-view reads, so reserve those names.
    shadowed = sorted(STABLE_CTX_VIEWS.intersection(_cte_names(query)))
    if shadowed:
        raise ValueError(f"CTE names must not shadow ctx views: {', '.join(shadowed)}")


def _cte_names(query: str) -> set[str]:
    index = _with_clause_start(query)
    if index is None:
        return set()
    names: set[str] = set()
    while index < len(query):
        index = _skip_whitespace(query, index)
        name, index = _read_identifier(query, index)
        if name is None:
            break
        names.add(name.lower())
        index = _skip_whitespace(query, index)
        if index < len(query) and query[index] == "(":
            index = _skip_balanced_parentheses(query, index)
            index = _skip_whitespace(query, index)
        if query[index : index + 2].lower() != "as":
            break
        index = _skip_whitespace(query, index + 2)
        if index >= len(query) or query[index] != "(":
            break
        index = _skip_balanced_parentheses(query, index)
        index = _skip_whitespace(query, index)
        if index < len(query) and query[index] == ",":
            index += 1
            continue
        break
    return names


def _with_clause_start(query: str) -> int | None:
    lowered = query.lower()
    if not lowered.startswith("with"):
        return None
    index = _skip_whitespace(query, 4)
    recursive_end = index + 9
    if lowered[index:recursive_end] == "recursive" and (
        recursive_end == len(query) or not _identifier_char(query[recursive_end])
    ):
        index = _skip_whitespace(query, index + 9)
    return index


def _skip_whitespace(query: str, index: int) -> int:
    while index < len(query) and query[index].isspace():
        index += 1
    return index


def _read_identifier(query: str, index: int) -> tuple[str | None, int]:
    if index >= len(query):
        return None, index
    if query[index] in {'"', "`"}:
        return _read_quoted_identifier(query, index, query[index], query[index])
    if query[index] == "[":
        return _read_quoted_identifier(query, index, "[", "]")
    start = index
    while index < len(query) and _identifier_char(query[index]):
        index += 1
    return (query[start:index] or None), index


def _identifier_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _read_quoted_identifier(query: str, index: int, opener: str, closer: str) -> tuple[str | None, int]:
    index += 1
    chars: list[str] = []
    while index < len(query):
        char = query[index]
        if char == closer:
            if index + 1 < len(query) and query[index + 1] == closer and opener != "[":
                chars.append(closer)
                index += 2
                continue
            return "".join(chars), index + 1
        chars.append(char)
        index += 1
    return None, index


def _skip_balanced_parentheses(query: str, index: int) -> int:
    depth = 0
    while index < len(query):
        char = query[index]
        if char in {'"', "'", "`"}:
            index = _skip_quoted(query, index, char, char)
            continue
        if char == "[":
            index = _skip_quoted(query, index, "[", "]")
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return index


def _skip_quoted(query: str, index: int, opener: str, closer: str) -> int:
    index += 1
    while index < len(query):
        if query[index] == closer:
            if index + 1 < len(query) and query[index + 1] == closer and opener != "[":
                index += 2
                continue
            return index + 1
        index += 1
    return index
