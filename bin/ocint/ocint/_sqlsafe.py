import re
import sqlite3
from typing import Any


READONLY_AUTHORIZE_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
}
if hasattr(sqlite3, "SQLITE_RECURSIVE"):
    READONLY_AUTHORIZE_ACTIONS.add(sqlite3.SQLITE_RECURSIVE)


def normalize_select_sql(sql: str) -> str:
    stripped = sql.strip()
    if not stripped:
        raise ValueError("SQL query is required")

    query = stripped[:-1].strip() if stripped.endswith(";") else stripped
    if ";" in query:
        raise ValueError("Only a single SQL statement is allowed")
    if not re.match(r"^(select|with)\b", query, re.IGNORECASE):
        raise ValueError("Only SELECT and WITH queries are allowed")
    return query


def _readonly_authorizer(action: int, _arg1: str | None, _arg2: str | None, _db: str | None, _source: str | None) -> int:
    # SQLite's authorizer is the last line of defense for WITH statements whose
    # leading keyword is read-like but whose body attempts writes or attachment.
    if action in READONLY_AUTHORIZE_ACTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def execute_readonly_query(connection: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    query = normalize_select_sql(sql)
    try:
        connection.set_authorizer(_readonly_authorizer)
        rows = connection.execute(query).fetchall()
    finally:
        connection.set_authorizer(None)
    return [dict(row) for row in rows]
