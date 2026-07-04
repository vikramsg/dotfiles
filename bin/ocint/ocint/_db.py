import sqlite3
from pathlib import Path
from typing import Any


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
