import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from ocint._db import inspect_schema, open_readonly_connection
from ocint._sqlsafe import execute_readonly_query
from ocint.opencode import schema as opencode_schema
from ocint.opencode.models import (
    OpenCodeJsonModel,
    OpenCodeMessageData,
    OpenCodeMessageRow,
    OpenCodePartData,
    OpenCodePartRow,
    OpenCodeSessionData,
    OpenCodeSessionRow,
    OpenCodeTranscriptEventRow,
    payload_paths,
)


class OpenCodeRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def readonly_connection(self) -> Iterator[sqlite3.Connection]:
        connection = open_readonly_connection(self.db_path)
        try:
            yield connection
        finally:
            connection.close()

    def schema(self) -> list[dict[str, Any]]:
        with self.readonly_connection() as connection:
            return inspect_schema(connection)

    def query(self, sql: str) -> list[dict[str, Any]]:
        with self.readonly_connection() as connection:
            return execute_readonly_query(connection, sql)

    def sessions(self) -> list[OpenCodeSessionRow]:
        with self.readonly_connection() as connection:
            if not _table_exists(connection, "session"):
                return []
            columns = _columns(connection, "session")
            data = opencode_schema.data_expr(columns)
            rows = connection.execute(
                f"""
                SELECT
                  {_expr(columns, ["id"], "id")},
                  {_expr(columns, ["parent_id", "parentID"], "parent_id")},
                  {_expr(columns, ["title"], "title")},
                  {opencode_schema.session_workspace_expr(columns, data)} AS {_quote("cwd")},
                  {_expr(columns, ["time_created", "timeCreated", "created_at", "createdAt"], "time_created")},
                  {_expr(columns, ["time_updated", "timeUpdated", "updated_at", "updatedAt"], "time_updated")},
                  {data} AS {_quote("data")}
                FROM {_quote("session")}
                """
            ).fetchall()
            return [_session_from_row(row) for row in rows]

    def messages(self) -> list[OpenCodeMessageRow]:
        with self.readonly_connection() as connection:
            return self._messages(connection)

    def parts(self) -> list[OpenCodePartRow]:
        with self.readonly_connection() as connection:
            return self._parts(connection)

    def usage_part_batches(
        self,
        *,
        start_ms: int | None,
        end_ms: int | None,
        batch_size: int,
    ) -> Iterator[list[OpenCodePartRow]]:
        """Yield time-windowed part rows in batches for state usage analytics."""
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")

        data_adapter = TypeAdapter(list[OpenCodePartData])
        with self.readonly_connection() as connection:
            query = _usage_parts_query(connection, start_ms=start_ms, end_ms=end_ms)
            if query is None:
                return
            sql, params = query
            session_by_message = _session_message_map(connection)
            cursor = connection.execute(sql, params)
            while rows := cursor.fetchmany(batch_size):
                yield _parts_from_rows(rows, session_by_message=session_by_message, data_adapter=data_adapter)

    def messages_by_id(self) -> dict[str, OpenCodeMessageRow]:
        return {message.id: message for message in self.messages()}

    def transcript_event_count(self) -> int:
        with self.readonly_connection() as connection:
            return _table_count(connection, "message") + _table_count(connection, "part")

    def transcript_event_batches(self, batch_size: int) -> Iterator[list[OpenCodeTranscriptEventRow]]:
        """Yield normalized message/part transcript rows without reading source events into one list."""
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")

        with self.readonly_connection() as connection:
            sql = _transcript_events_sql(connection)
            if sql is None:
                return
            cursor = connection.execute(sql)
            while rows := cursor.fetchmany(batch_size):
                yield [_transcript_event_from_row(row) for row in rows]

    def find_session(self, session_id: str) -> OpenCodeSessionRow | None:
        return next((session for session in self.sessions() if session.id == session_id), None)

    def table_count(self, table: str) -> int:
        with self.readonly_connection() as connection:
            return _table_count(connection, table)

    def _messages(self, connection: sqlite3.Connection) -> list[OpenCodeMessageRow]:
        if not _table_exists(connection, "message"):
            return []
        columns = _columns(connection, "message")
        session_by_message = _session_message_map(connection)
        rows = connection.execute(
            f"""
            SELECT
              {_expr(columns, ["id"], "id")},
              {_expr(columns, ["session_id", "sessionID"], "session_id")},
              {_expr(columns, ["time_created", "timeCreated", "created_at", "createdAt"], "time_created")},
              {_expr(columns, ["data"], "data", "'{}'")}
            FROM {_quote("message")}
            """
        ).fetchall()
        messages = []
        for row in rows:
            session_id = _optional_str(row["session_id"]) or session_by_message.get(str(row["id"]))
            messages.append(
                OpenCodeMessageRow(
                    id=str(row["id"]),
                    session_id=session_id,
                    time_created=_optional_int(row["time_created"]),
                    data=_parse_payload(OpenCodeMessageData, row["data"]),
                )
            )
        return messages

    def _parts(self, connection: sqlite3.Connection) -> list[OpenCodePartRow]:
        if not _table_exists(connection, "part"):
            return []
        columns = _columns(connection, "part")
        session_by_message = _session_message_map(connection)
        rows = connection.execute(
            f"""
            SELECT
              {_expr(columns, ["id"], "id")},
              {_expr(columns, ["message_id", "messageID"], "message_id")},
              {_expr(columns, ["session_id", "sessionID"], "session_id")},
              {_expr(columns, ["time_created", "timeCreated", "created_at", "createdAt"], "time_created")},
              {_expr(columns, ["time_updated", "timeUpdated", "updated_at", "updatedAt"], "time_updated")},
              {_expr(columns, ["data"], "data", "'{}'")}
            FROM {_quote("part")}
            """
        ).fetchall()
        parts = []
        for row in rows:
            message_id = _optional_str(row["message_id"])
            session_id = _optional_str(row["session_id"]) or (
                session_by_message.get(message_id) if message_id else None
            )
            parts.append(
                OpenCodePartRow(
                    id=str(row["id"]),
                    message_id=message_id,
                    session_id=session_id,
                    time_created=_optional_int(row["time_created"]),
                    time_updated=_optional_int(row["time_updated"]),
                    data=_parse_payload(OpenCodePartData, row["data"]),
                )
            )
        return parts


def _session_from_row(row: sqlite3.Row) -> OpenCodeSessionRow:
    data = _parse_payload(OpenCodeSessionData, row["data"])
    return OpenCodeSessionRow(
        id=str(row["id"]),
        parent_id=_optional_str(row["parent_id"]),
        title=_optional_str(row["title"]) or data.title,
        cwd=_optional_str(row["cwd"]) or data.directory or data.workspace or data.cwd or data.path,
        time_created=_optional_int(row["time_created"]),
        time_updated=_optional_int(row["time_updated"]),
        data=data,
    )


def _transcript_events_sql(connection: sqlite3.Connection) -> str | None:
    selects = [
        select
        for select in [_transcript_message_select(connection), _transcript_part_select(connection)]
        if select is not None
    ]
    if not selects:
        return None
    union_sql = "\nUNION ALL\n".join(selects)
    return f"""
    SELECT *
    FROM (
      {union_sql}
    )
    ORDER BY sort_time, source_table, id
    """


def _transcript_message_select(connection: sqlite3.Connection) -> str | None:
    if not _table_exists(connection, "message"):
        return None
    columns = _columns(connection, "message")
    row_alias = "message"
    id_expr = opencode_schema.column_expr(columns, ["id"], table_alias=row_alias)
    time_created = opencode_schema.column_expr(
        columns,
        ["time_created", "timeCreated", "created_at", "createdAt"],
        table_alias=row_alias,
    )
    session_id, session_join = _session_id_expr(
        connection,
        row_alias=row_alias,
        row_columns=columns,
        message_id_expr=id_expr,
    )
    data = opencode_schema.data_expr(columns, table_alias=row_alias)
    return f"""
    SELECT
      {id_expr} AS {_quote("id")},
      'message' AS {_quote("source_table")},
      {session_id} AS {_quote("session_id")},
      {id_expr} AS {_quote("message_id")},
      {time_created} AS {_quote("time_created")},
      {time_created} AS {_quote("time_updated")},
      {data} AS {_quote("data")},
      COALESCE({time_created}, 0) AS {_quote("sort_time")}
    FROM {_quote("message")} AS {_quote(row_alias)}
    {session_join}
    """


def _transcript_part_select(connection: sqlite3.Connection) -> str | None:
    if not _table_exists(connection, "part"):
        return None
    columns = _columns(connection, "part")
    row_alias = "part"
    id_expr = opencode_schema.column_expr(columns, ["id"], table_alias=row_alias)
    message_id = opencode_schema.column_expr(columns, ["message_id", "messageID"], table_alias=row_alias)
    time_created = opencode_schema.column_expr(
        columns,
        ["time_created", "timeCreated", "created_at", "createdAt"],
        table_alias=row_alias,
    )
    time_updated = opencode_schema.column_expr(
        columns,
        ["time_updated", "timeUpdated", "updated_at", "updatedAt"],
        table_alias=row_alias,
    )
    session_id, session_join = _session_id_expr(
        connection,
        row_alias=row_alias,
        row_columns=columns,
        message_id_expr=message_id,
    )
    data = opencode_schema.data_expr(columns, table_alias=row_alias)
    return f"""
    SELECT
      {id_expr} AS {_quote("id")},
      'part' AS {_quote("source_table")},
      {session_id} AS {_quote("session_id")},
      {message_id} AS {_quote("message_id")},
      {time_created} AS {_quote("time_created")},
      {time_updated} AS {_quote("time_updated")},
      {data} AS {_quote("data")},
      COALESCE({time_created}, 0) AS {_quote("sort_time")}
    FROM {_quote("part")} AS {_quote(row_alias)}
    {session_join}
    """


def _session_id_expr(
    connection: sqlite3.Connection,
    *,
    row_alias: str,
    row_columns: list[str],
    message_id_expr: str,
) -> tuple[str, str]:
    direct_session_id = opencode_schema.column_expr(
        row_columns,
        ["session_id", "sessionID"],
        table_alias=row_alias,
    )
    direct_session_id = _nullif_empty(direct_session_id)
    fallback_session_id, session_join = _session_message_fallback_join(connection, message_id_expr)
    if fallback_session_id is None:
        return direct_session_id, ""
    if direct_session_id == "NULL":
        return fallback_session_id, session_join
    return opencode_schema.coalesce([direct_session_id, fallback_session_id]), session_join


def _session_message_fallback_join(
    connection: sqlite3.Connection,
    message_id_expr: str,
) -> tuple[str | None, str]:
    if message_id_expr == "NULL" or not _table_exists(connection, "session_message"):
        return None, ""
    columns = _columns(connection, "session_message")
    session_col = _first_column(columns, ["session_id", "sessionID"])
    message_col = _first_column(columns, ["message_id", "messageID"])
    if session_col is None or message_col is None:
        return None, ""
    map_alias = "session_message_map"
    fallback_session_id = f"{_quote(map_alias)}.{_quote('session_id')}"
    join = f"""
    LEFT JOIN (
      SELECT
        {_quote(message_col)} AS {_quote("message_id")},
        MIN({_quote(session_col)}) AS {_quote("session_id")}
      FROM {_quote("session_message")}
      GROUP BY {_quote(message_col)}
    ) AS {_quote(map_alias)}
      ON {_quote(map_alias)}.{_quote("message_id")} = {message_id_expr}
    """
    return fallback_session_id, join


def _nullif_empty(expression: str) -> str:
    if expression == "NULL":
        return expression
    return f"NULLIF({expression}, '')"


def _transcript_event_from_row(row: sqlite3.Row) -> OpenCodeTranscriptEventRow:
    source_table = str(row["source_table"])
    if source_table == "message":
        data = _parse_payload(OpenCodeMessageData, row["data"])
        return OpenCodeTranscriptEventRow(
            id=str(row["id"]),
            source_table="message",
            session_id=_optional_str(row["session_id"]),
            message_id=str(row["id"]),
            time_created=_optional_int(row["time_created"]),
            time_updated=_optional_int(row["time_created"]),
            event_type=data.role or "message",
            data=data,
            source_path=_first_path(data),
        )
    if source_table == "part":
        data = _parse_payload(OpenCodePartData, row["data"])
        return OpenCodeTranscriptEventRow(
            id=str(row["id"]),
            source_table="part",
            session_id=_optional_str(row["session_id"]),
            message_id=_optional_str(row["message_id"]),
            time_created=_optional_int(row["time_created"]),
            time_updated=_optional_int(row["time_updated"]),
            event_type=data.type or "part",
            data=data,
            source_path=_first_path(data),
        )
    raise ValueError(f"Unsupported OpenCode transcript source table: {source_table}")


def _usage_parts_query(
    connection: sqlite3.Connection,
    *,
    start_ms: int | None,
    end_ms: int | None,
) -> tuple[str, tuple[int, ...]] | None:
    if not _table_exists(connection, "part"):
        return None
    columns = _columns(connection, "part")
    time_expr = opencode_schema.column_expr(columns, ["time_created", "timeCreated", "created_at", "createdAt"])
    if time_expr == "NULL":
        return None
    data = _object_data_expr(columns)
    where = [f"{time_expr} IS NOT NULL"]
    params: list[int] = []
    if start_ms is not None:
        where.append(f"{time_expr} >= ?")
        params.append(start_ms)
    if end_ms is not None:
        where.append(f"{time_expr} < ?")
        params.append(end_ms)
    return (
        f"""
        SELECT
          {_expr(columns, ["id"], "id")},
          {_expr(columns, ["message_id", "messageID"], "message_id")},
          {_expr(columns, ["session_id", "sessionID"], "session_id")},
          {_expr(columns, ["time_created", "timeCreated", "created_at", "createdAt"], "time_created")},
          {_expr(columns, ["time_updated", "timeUpdated", "updated_at", "updatedAt"], "time_updated")},
          {data} AS {_quote("data")}
        FROM {_quote("part")}
        WHERE {" AND ".join(where)}
        ORDER BY {time_expr}, {_quote("id")}
        """,
        tuple(params),
    )


def _object_data_expr(columns: list[str]) -> str:
    data = opencode_schema.column_expr(columns, ["data"])
    if data == "NULL":
        return "'{}'"
    # Batch validation expects every payload to be a JSON object. Preserve the
    # old per-row tolerant parsing behavior by converting invalid or non-object
    # payloads to an empty object before building the batch JSON array.
    return f"CASE WHEN json_valid({data}) THEN CASE WHEN json_type({data}) = 'object' THEN {data} ELSE '{{}}' END ELSE '{{}}' END"


def _parts_from_rows(
    rows: Sequence[sqlite3.Row],
    *,
    session_by_message: dict[str, str],
    data_adapter: TypeAdapter[list[OpenCodePartData]],
) -> list[OpenCodePartRow]:
    data_items = data_adapter.validate_json("[" + ",".join(str(row["data"]) for row in rows) + "]")
    parts = []
    for row, data in zip(rows, data_items, strict=True):
        message_id = _optional_str(row["message_id"])
        session_id = _optional_str(row["session_id"]) or (session_by_message.get(message_id) if message_id else None)
        parts.append(
            OpenCodePartRow(
                id=str(row["id"]),
                message_id=message_id,
                session_id=session_id,
                time_created=_optional_int(row["time_created"]),
                time_updated=_optional_int(row["time_updated"]),
                data=data,
            )
        )
    return parts


def _table_count(connection: sqlite3.Connection, table: str) -> int:
    if not _table_exists(connection, table):
        return 0
    return int(connection.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()[0] or 0)


def _first_path(payload: OpenCodeJsonModel) -> str | None:
    paths = payload_paths(payload)
    return paths[0] if paths else None


def _session_message_map(connection: sqlite3.Connection) -> dict[str, str]:
    if not _table_exists(connection, "session_message"):
        return {}
    columns = _columns(connection, "session_message")
    session_col = _first_column(columns, ["session_id", "sessionID"])
    message_col = _first_column(columns, ["message_id", "messageID"])
    if session_col is None or message_col is None:
        return {}
    rows = connection.execute(
        f"SELECT {_quote(message_col)} AS message_id, {_quote(session_col)} AS session_id FROM {_quote('session_message')}"
    ).fetchall()
    return {str(row["message_id"]): str(row["session_id"]) for row in rows if row["message_id"] is not None}


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return opencode_schema.table_exists(connection, table)


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return opencode_schema.columns(connection, table)


def _expr(columns: list[str], candidates: list[str], alias: str, default: str = "NULL") -> str:
    return opencode_schema.column_select(columns, candidates, alias, default)


def _first_column(columns: list[str], candidates: list[str]) -> str | None:
    return opencode_schema.first_column(columns, candidates)


def _quote(identifier: str) -> str:
    return opencode_schema.quote(identifier)


def _parse_payload[JsonModelT: OpenCodeJsonModel](model: type[JsonModelT], raw: Any) -> JsonModelT:
    if raw in (None, ""):
        return model.model_validate({})
    if isinstance(raw, bytes):
        raw = raw.decode()
    if isinstance(raw, str):
        try:
            return model.model_validate_json(raw)
        except ValidationError:
            return model.model_validate({})
    return model.model_validate(raw)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value)
    return result if result else None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)
