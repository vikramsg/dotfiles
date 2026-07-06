import sqlite3
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, NamedTuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from ocint._sqlsafe import normalize_select_sql
from ocint.ctx.schema import STABLE_CTX_VIEW_COLUMNS, STABLE_CTX_VIEWS

Authorizer = Callable[[int, str | None, str | None, str | None, str | None], int]

_ALLOWED_SANDBOX_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
}
if hasattr(sqlite3, "SQLITE_RECURSIVE"):
    _ALLOWED_SANDBOX_ACTIONS.add(sqlite3.SQLITE_RECURSIVE)

_SANDBOX_INTEGER_COLUMNS = {"time_created", "time_updated", "sessions", "events", "imported_at"}


class CtxSqlRepository:
    def __init__(self, session: Session, *, db_path: Path) -> None:
        self._session = session
        self.db_path = db_path

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


class _SqlToken(NamedTuple):
    kind: str
    value: str


def _cte_names(query: str) -> set[str]:
    tokens = _sql_tokens(query)
    names: set[str] = set()
    for index, token in enumerate(tokens):
        if token.kind == "identifier" and token.value == "with":
            names.update(_cte_names_after_with(tokens, index + 1))
    return names


def _cte_names_after_with(tokens: list[_SqlToken], index: int) -> set[str]:
    names: set[str] = set()
    if _token_value(tokens, index) == "recursive":
        index += 1
    while index < len(tokens):
        token = tokens[index]
        if token.kind != "identifier":
            return names
        names.add(token.value)
        index += 1
        if _is_symbol(tokens, index, "("):
            index = _skip_token_parentheses(tokens, index)
        if _token_value(tokens, index) != "as":
            return names
        index += 1
        if _token_value(tokens, index) == "not":
            index += 1
        if _token_value(tokens, index) == "materialized":
            index += 1
        if not _is_symbol(tokens, index, "("):
            return names
        index = _skip_token_parentheses(tokens, index)
        if _is_symbol(tokens, index, ","):
            index += 1
            continue
        return names
    return names


def _sql_tokens(query: str) -> list[_SqlToken]:
    tokens: list[_SqlToken] = []
    index = 0
    while index < len(query):
        char = query[index]
        if char.isspace():
            index += 1
            continue
        if query.startswith("--", index):
            index = _skip_line_comment(query, index + 2)
            continue
        if query.startswith("/*", index):
            index = _skip_block_comment(query, index + 2)
            continue
        if char == "'":
            index = _skip_quoted(query, index, "'", "'")
            continue
        if char in {'"', "`"}:
            value, index = _read_quoted_identifier(query, index, char, char)
            if value is not None:
                tokens.append(_SqlToken("identifier", value.lower()))
            continue
        if char == "[":
            value, index = _read_quoted_identifier(query, index, "[", "]")
            if value is not None:
                tokens.append(_SqlToken("identifier", value.lower()))
            continue
        if _identifier_char(char):
            start = index
            while index < len(query) and _identifier_char(query[index]):
                index += 1
            tokens.append(_SqlToken("identifier", query[start:index].lower()))
            continue
        if char in "(),":
            tokens.append(_SqlToken("symbol", char))
        index += 1
    return tokens


def _skip_line_comment(query: str, index: int) -> int:
    while index < len(query) and query[index] not in "\r\n":
        index += 1
    return index


def _skip_block_comment(query: str, index: int) -> int:
    end = query.find("*/", index)
    return len(query) if end == -1 else end + 2


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


def _skip_token_parentheses(tokens: list[_SqlToken], index: int) -> int:
    depth = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "symbol" and token.value == "(":
            depth += 1
        elif token.kind == "symbol" and token.value == ")":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return index


def _token_value(tokens: list[_SqlToken], index: int) -> str | None:
    if index >= len(tokens):
        return None
    return tokens[index].value


def _is_symbol(tokens: list[_SqlToken], index: int, value: str) -> bool:
    return index < len(tokens) and tokens[index].kind == "symbol" and tokens[index].value == value


def _identifier_char(char: str) -> bool:
    return char.isalnum() or char == "_"
