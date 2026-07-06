import sqlite3
from collections.abc import Callable, Iterable, Mapping
from typing import NamedTuple

from ocint._sqlsafe import normalize_select_sql
from ocint.ctx.sql.models import CtxSqlConfig, CtxSqlStableView
from ocint.ctx.sql.repository import CtxSqlRepository


def run_ctx_sql(repository: CtxSqlRepository, sql: str, config: CtxSqlConfig) -> list[dict[str, object]]:
    query = normalize_select_sql(sql)
    _reject_shadowed_ctx_views(query, config)
    rows_by_projection = repository.load_stable_projection_rows(config)
    sandbox = _stable_projection_sandbox(rows_by_projection, config)
    try:
        sandbox.set_authorizer(_stable_projection_authorizer(config))
        rows = sandbox.execute(query).fetchall()
    finally:
        sandbox.set_authorizer(None)
        sandbox.close()
    return [dict(row) for row in rows]


def _stable_projection_sandbox(
    rows_by_projection: Mapping[str, Iterable[Mapping[str, object]]], config: CtxSqlConfig
) -> sqlite3.Connection:
    """Build a transient SQL environment containing only public ctx projections."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        for view in config.stable_views:
            _create_sandbox_table(connection, view)
            _insert_sandbox_rows(connection, view, rows_by_projection.get(view.name, []))
        # `query_only` protects the materialized sandbox even if a future SQL
        # normalizer bug lets a write-like statement reach sqlite3 execution.
        connection.execute("PRAGMA query_only = ON")
    except Exception:
        connection.close()
        raise
    return connection


def _create_sandbox_table(connection: sqlite3.Connection, view: CtxSqlStableView) -> None:
    column_defs = ", ".join(f"{_quote_identifier(column.name)} {column.storage_type.value}" for column in view.columns)
    connection.execute(f"CREATE TABLE {_quote_identifier(view.name)} ({column_defs})")


def _insert_sandbox_rows(
    connection: sqlite3.Connection,
    view: CtxSqlStableView,
    rows: Iterable[Mapping[str, object]],
) -> None:
    materialized_rows = [dict(row) for row in rows]
    if not materialized_rows:
        return
    column_sql = ", ".join(_quote_identifier(column.name) for column in view.columns)
    parameter_sql = ", ".join(f":{column.name}" for column in view.columns)
    connection.executemany(
        f"INSERT INTO {_quote_identifier(view.name)} ({column_sql}) VALUES ({parameter_sql})",
        materialized_rows,
    )


def _stable_projection_authorizer(
    config: CtxSqlConfig,
) -> Callable[[int, str | None, str | None, str | None, str | None], int]:
    """Allow reads only from materialized stable projection tables and columns."""
    allowed_actions = _allowed_sandbox_actions()
    allowed_columns = {view.name: frozenset(column.name for column in view.columns) for view in config.stable_views}

    def authorize(action: int, arg1: str | None, arg2: str | None, _db: str | None, _source: str | None) -> int:
        if action not in allowed_actions:
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


def _allowed_sandbox_actions() -> set[int]:
    allowed_actions = {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
    }
    if hasattr(sqlite3, "SQLITE_RECURSIVE"):
        allowed_actions.add(sqlite3.SQLITE_RECURSIVE)
    return allowed_actions


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def _normalize_identifier(identifier: str | None) -> str | None:
    return identifier.lower() if identifier is not None else None


def _reject_shadowed_ctx_views(query: str, config: CtxSqlConfig) -> None:
    # A CTE named like an approved view can make SQLite's authorizer report
    # source=<ctx view name> for non-view reads, so reserve those names.
    stable_view_names = {view.name for view in config.stable_views}
    shadowed = sorted(stable_view_names.intersection(_cte_names(query)))
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
