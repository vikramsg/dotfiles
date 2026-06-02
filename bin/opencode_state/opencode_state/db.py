import re
import sqlite3
from pathlib import Path
from typing import Any


READONLY_AUTHORIZE_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
}
if hasattr(sqlite3, "SQLITE_RECURSIVE"):
    READONLY_AUTHORIZE_ACTIONS.add(sqlite3.SQLITE_RECURSIVE)


def reject_memory_db_path(db_path: str | Path) -> None:
    if str(db_path) == ":memory:":
        raise ValueError(":memory: is not a valid OpenCode DB target")


def normalize_db_path(db_path: str | Path) -> Path:
    reject_memory_db_path(db_path)
    path = Path(db_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"OpenCode DB does not exist: {path}")
    return path


def open_readonly_connection(db_path: str | Path) -> sqlite3.Connection:
    path = normalize_db_path(db_path)
    uri = f"{path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def inspect_schema(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT m.name AS table_name, p.name AS column_name, p.type AS column_type, p.pk AS primary_key
        FROM sqlite_master AS m
        JOIN pragma_table_info(m.name) AS p
        WHERE m.type = 'table'
        ORDER BY m.name, p.cid
        """
    ).fetchall()
    return [dict(row) for row in rows]


def safe_select_query(sql: str) -> str:
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
    if action in READONLY_AUTHORIZE_ACTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def run_select_query(connection: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    query = safe_select_query(sql)
    try:
        connection.set_authorizer(_readonly_authorizer)
        rows = connection.execute(query).fetchall()
    finally:
        connection.set_authorizer(None)
    return [dict(row) for row in rows]
