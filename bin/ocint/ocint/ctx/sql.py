import sqlite3
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from ocint._sqlsafe import normalize_select_sql
from ocint.ctx.protocols import CtxSqlProjectionRepositoryProtocol
from ocint.ctx.schema import STABLE_CTX_VIEW_COLUMNS, STABLE_CTX_VIEWS

ALLOWED_CTX_VIEWS = STABLE_CTX_VIEWS
Authorizer = Callable[[int, str | None, str | None, str | None, str | None], int]

_ALLOWED_SANDBOX_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
}
if hasattr(sqlite3, "SQLITE_RECURSIVE"):
    _ALLOWED_SANDBOX_ACTIONS.add(sqlite3.SQLITE_RECURSIVE)

_SANDBOX_INTEGER_COLUMNS = {"time_created", "time_updated", "sessions", "events", "imported_at"}


def run_ctx_sql(repository: CtxSqlProjectionRepositoryProtocol, sql: str) -> list[dict[str, Any]]:
    query = normalize_select_sql(sql)
    _reject_shadowed_ctx_views(query)
    rows_by_projection = repository.load_stable_projection_rows()
    sandbox = _stable_projection_sandbox(rows_by_projection)
    try:
        sandbox.set_authorizer(_stable_projection_authorizer())
        rows = sandbox.execute(query).fetchall()
    finally:
        sandbox.set_authorizer(None)
        sandbox.close()
    return [dict(row) for row in rows]


def _stable_projection_sandbox(rows_by_projection: Mapping[str, Iterable[Mapping[str, Any]]]) -> sqlite3.Connection:
    """Materialize public ctx projections so arbitrary SELECTs never touch DuckDB or internal tables."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        for name, columns in STABLE_CTX_VIEW_COLUMNS.items():
            _create_sandbox_table(connection, name, columns)
            _insert_sandbox_rows(connection, name, columns, rows_by_projection.get(name, []))
        # `query_only` protects the sandbox if the SQL normalizer misses a
        # write-like construct in a future SQLite grammar change.
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
    _ = opener
    index += 1
    while index < len(query):
        if query[index] == closer:
            if index + 1 < len(query) and query[index + 1] == closer and closer != "]":
                index += 2
                continue
            return index + 1
        index += 1
    return index
