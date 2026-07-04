import sqlite3
from collections.abc import Callable
from typing import Any

from ocint._sqlsafe import normalize_select_sql
from ocint.ctx.views import install_ctx_views
from ocint.opencode.repository import OpenCodeRepository

ALLOWED_CTX_VIEWS = frozenset({"ctx_sessions", "ctx_events", "ctx_files_touched", "ctx_sources"})
Authorizer = Callable[[int, str | None, str | None, str | None, str | None], int]

_ALLOWED_CTX_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
}
if hasattr(sqlite3, "SQLITE_RECURSIVE"):
    _ALLOWED_CTX_ACTIONS.add(sqlite3.SQLITE_RECURSIVE)


def run_ctx_sql(repository: OpenCodeRepository, sql: str) -> list[dict[str, Any]]:
    with repository.readonly_connection() as connection:
        install_ctx_views(connection)
        return execute_ctx_view_query(connection, sql)


def execute_ctx_view_query(connection: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    query = normalize_select_sql(sql)
    _reject_shadowed_ctx_views(query)
    try:
        connection.set_authorizer(_ctx_view_authorizer())
        rows = connection.execute(query).fetchall()
    finally:
        connection.set_authorizer(None)
    return [dict(row) for row in rows]


def _ctx_view_authorizer() -> Authorizer:
    view_expanded_tables: set[str] = set()

    def authorize(action: int, arg1: str | None, arg2: str | None, _db: str | None, source: str | None) -> int:
        if action not in _ALLOWED_CTX_ACTIONS:
            return sqlite3.SQLITE_DENY
        if action != sqlite3.SQLITE_READ:
            return sqlite3.SQLITE_OK

        table = _normalize_identifier(arg1)
        source_view = _normalize_identifier(source)
        if table in ALLOWED_CTX_VIEWS:
            return sqlite3.SQLITE_OK
        # SQLite usually reports base-table reads performed while expanding a
        # view with source=<view name>. For aggregates such as COUNT(*), it may
        # later ask for a source-less table read; allow only tables already seen
        # through approved view expansion in this statement.
        if source_view in ALLOWED_CTX_VIEWS:
            if table is not None:
                view_expanded_tables.add(table)
            return sqlite3.SQLITE_OK
        if source_view is None and arg2 == "" and table in view_expanded_tables:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    return authorize


def _normalize_identifier(identifier: str | None) -> str | None:
    return identifier.lower() if identifier is not None else None


def _reject_shadowed_ctx_views(query: str) -> None:
    # A CTE named like an approved view can make SQLite's authorizer report
    # source=<ctx view name> for non-view reads, so reserve those names.
    shadowed = sorted(ALLOWED_CTX_VIEWS.intersection(_cte_names(query)))
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
