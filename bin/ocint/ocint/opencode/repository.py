import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ocint._db import inspect_schema, open_readonly_connection
from ocint._sqlsafe import execute_readonly_query
from ocint.opencode import schema as opencode_schema
from ocint.opencode.models import (
    OpenCodeEventData,
    OpenCodeEventRow,
    OpenCodeJsonModel,
    OpenCodeMessageData,
    OpenCodeMessageRow,
    OpenCodePartData,
    OpenCodePartRow,
    OpenCodeSessionData,
    OpenCodeSessionRow,
    OpenCodeUnifiedEventRow,
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

    def events(self) -> list[OpenCodeEventRow]:
        with self.readonly_connection() as connection:
            return self._events(connection)

    def messages_by_id(self) -> dict[str, OpenCodeMessageRow]:
        return {message.id: message for message in self.messages()}

    def all_unified_events(self) -> list[OpenCodeUnifiedEventRow]:
        events: list[OpenCodeUnifiedEventRow] = []
        events.extend(_unified_message(message) for message in self.messages())
        events.extend(_unified_part(part) for part in self.parts())
        events.extend(_unified_event(event) for event in self.events())
        return sorted(events, key=lambda event: (event.time_created or 0, event.source_table, event.id))

    def iter_unified_events_desc(self, *, session_ids: set[str] | None = None) -> Iterator[OpenCodeUnifiedEventRow]:
        with self.readonly_connection() as connection:
            query_and_params = _unified_events_query(connection, session_ids=session_ids)
            if query_and_params is None:
                return
            query, params = query_and_params
            if query is None:
                return
            session_by_message = _session_message_map(connection)
            for row in connection.execute(query, params):
                event = _unified_from_query_row(row, session_by_message=session_by_message)
                if event is not None:
                    yield event

    def session_events(self, session_id: str) -> list[OpenCodeUnifiedEventRow]:
        return sorted(
            self.iter_unified_events_desc(session_ids={session_id}),
            key=lambda event: (event.time_created or 0, event.source_table, event.id),
        )

    def find_session(self, session_id: str) -> OpenCodeSessionRow | None:
        return next((session for session in self.sessions() if session.id == session_id), None)

    def find_event(self, event_id: str) -> OpenCodeUnifiedEventRow | None:
        with self.readonly_connection() as connection:
            session_by_message = _session_message_map(connection)
            for table in ["event", "part", "message"]:
                row = _row_by_id(connection, table, event_id)
                if row is None:
                    continue
                event = _unified_from_query_row(row, session_by_message=session_by_message)
                if event is not None:
                    return event
            return None

    def table_count(self, table: str) -> int:
        with self.readonly_connection() as connection:
            if not _table_exists(connection, table):
                return 0
            return int(connection.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()[0] or 0)

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

    def _events(self, connection: sqlite3.Connection) -> list[OpenCodeEventRow]:
        if not _table_exists(connection, "event"):
            return []
        columns = _columns(connection, "event")
        data = opencode_schema.data_expr(columns)
        rows = connection.execute(
            f"""
            SELECT
              {_expr(columns, ["id"], "id")},
              {opencode_schema.event_session_id_expr(columns, data)} AS {_quote("session_id")},
              {opencode_schema.event_type_expr(columns, data)} AS {_quote("event_type")},
              {opencode_schema.event_time_created_expr(columns, data)} AS {_quote("time_created")},
              {_expr(columns, ["time_updated", "timeUpdated", "updated_at", "updatedAt"], "time_updated")},
              {data} AS {_quote("data")}
            FROM {_quote("event")}
            """
        ).fetchall()
        return [
            OpenCodeEventRow(
                id=str(row["id"]),
                session_id=_optional_str(row["session_id"]),
                event_type=_optional_str(row["event_type"]) or "event",
                time_created=_optional_int(row["time_created"]),
                time_updated=_optional_int(row["time_updated"]),
                data=_parse_payload(OpenCodeEventData, row["data"]),
            )
            for row in rows
        ]


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


def _unified_message(message: OpenCodeMessageRow) -> OpenCodeUnifiedEventRow:
    return OpenCodeUnifiedEventRow(
        id=message.id,
        source_table="message",
        session_id=message.session_id,
        message_id=message.id,
        time_created=message.time_created,
        time_updated=message.time_created,
        event_type=message.data.role or "message",
        data=message.data,
        source_path=_first_path(message.data),
    )


def _unified_part(part: OpenCodePartRow) -> OpenCodeUnifiedEventRow:
    return OpenCodeUnifiedEventRow(
        id=part.id,
        source_table="part",
        session_id=part.session_id,
        message_id=part.message_id,
        time_created=part.time_created,
        time_updated=part.time_updated,
        event_type=part.data.type or "part",
        data=part.data,
        source_path=_first_path(part.data),
    )


def _unified_event(event: OpenCodeEventRow) -> OpenCodeUnifiedEventRow:
    return OpenCodeUnifiedEventRow(
        id=event.id,
        source_table="event",
        session_id=event.session_id,
        time_created=event.time_created,
        time_updated=event.time_updated,
        event_type=event.event_type or event.data.type or "event",
        data=event.data,
        source_path=_first_path(event.data),
    )


def _unified_from_query_row(row: sqlite3.Row, *, session_by_message: dict[str, str]) -> OpenCodeUnifiedEventRow | None:
    source_table = str(row["source_table"])
    raw_data = row["data"]
    if source_table == "message":
        message = OpenCodeMessageRow(
            id=str(row["id"]),
            session_id=_optional_str(row["session_id"]) or session_by_message.get(str(row["id"])),
            time_created=_optional_int(row["time_created"]),
            data=_parse_payload(OpenCodeMessageData, raw_data),
        )
        return _unified_message(message)
    if source_table == "part":
        message_id = _optional_str(row["message_id"])
        part = OpenCodePartRow(
            id=str(row["id"]),
            message_id=message_id,
            session_id=_optional_str(row["session_id"]) or (session_by_message.get(message_id) if message_id else None),
            time_created=_optional_int(row["time_created"]),
            time_updated=_optional_int(row["time_updated"]),
            data=_parse_payload(OpenCodePartData, raw_data),
        )
        return _unified_part(part)
    if source_table == "event":
        event = OpenCodeEventRow(
            id=str(row["id"]),
            session_id=_optional_str(row["session_id"]),
            event_type=_optional_str(row["event_type"]) or "event",
            time_created=_optional_int(row["time_created"]),
            time_updated=_optional_int(row["time_updated"]),
            data=_parse_payload(OpenCodeEventData, raw_data),
        )
        return _unified_event(event)
    return None


def _row_by_id(connection: sqlite3.Connection, table: str, row_id: str) -> sqlite3.Row | None:
    if not _table_exists(connection, table):
        return None
    columns = _columns(connection, table)
    if _first_column(columns, ["id"]) is None:
        return None
    data = opencode_schema.data_expr(columns)
    if table == "message":
        return connection.execute(
            f"""
            SELECT 'message' AS source_table,
                   {_column_select(columns, ["id"], "id")},
                   {_column_select(columns, ["session_id", "sessionID"], "session_id")},
                   CAST(NULL AS TEXT) AS message_id,
                   {opencode_schema.coalesce([opencode_schema.json_extract(data, "$.role"), "'message'"])} AS {_quote("event_type")},
                   {_column_select(columns, ["time_created", "timeCreated", "created_at", "createdAt"], "time_created")},
                   {_column_select(columns, ["time_updated", "timeUpdated", "updated_at", "updatedAt"], "time_updated")},
                   {data} AS {_quote("data")}
            FROM {_quote("message")}
            WHERE {_quote(_first_column(columns, ["id"]) or "id")} = ?
            LIMIT 1
            """,
            (row_id,),
        ).fetchone()
    if table == "part":
        return connection.execute(
            f"""
            SELECT 'part' AS source_table,
                   {_column_select(columns, ["id"], "id")},
                   {_column_select(columns, ["session_id", "sessionID"], "session_id")},
                   {_column_select(columns, ["message_id", "messageID"], "message_id")},
                   {opencode_schema.coalesce([opencode_schema.json_extract(data, "$.type"), "'part'"])} AS {_quote("event_type")},
                   {_column_select(columns, ["time_created", "timeCreated", "created_at", "createdAt"], "time_created")},
                   {_column_select(columns, ["time_updated", "timeUpdated", "updated_at", "updatedAt"], "time_updated")},
                   {data} AS {_quote("data")}
            FROM {_quote("part")}
            WHERE {_quote(_first_column(columns, ["id"]) or "id")} = ?
            LIMIT 1
            """,
            (row_id,),
        ).fetchone()
    if table == "event":
        return connection.execute(
            f"""
            SELECT 'event' AS source_table,
                   {_column_select(columns, ["id"], "id")},
                   {opencode_schema.event_session_id_expr(columns, data)} AS {_quote("session_id")},
                   CAST(NULL AS TEXT) AS message_id,
                   {opencode_schema.event_type_expr(columns, data)} AS {_quote("event_type")},
                   {opencode_schema.event_time_created_expr(columns, data)} AS {_quote("time_created")},
                   {_column_select(columns, ["time_updated", "timeUpdated", "updated_at", "updatedAt"], "time_updated")},
                   {data} AS {_quote("data")}
            FROM {_quote("event")}
            WHERE {_quote(_first_column(columns, ["id"]) or "id")} = ?
            LIMIT 1
            """,
            (row_id,),
        ).fetchone()
    return None


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


def _unified_events_query(
    connection: sqlite3.Connection, *, session_ids: set[str] | None = None
) -> tuple[str, list[str]] | None:
    branches: list[str] = []
    params: list[str] = []
    if _table_exists(connection, "message"):
        columns = _columns(connection, "message")
        data = opencode_schema.data_expr(columns)
        where, where_params = _session_filter(columns, session_ids)
        if where is not None:
            params.extend(where_params)
            branches.append(
                f"""
                SELECT 'message' AS source_table,
                       {_column_select(columns, ["id"], "id")},
                       {_column_select(columns, ["session_id", "sessionID"], "session_id")},
                       CAST(NULL AS TEXT) AS message_id,
                       {opencode_schema.coalesce([opencode_schema.json_extract(data, "$.role"), "'message'"])} AS {_quote("event_type")},
                       {_column_select(columns, ["time_created", "timeCreated", "created_at", "createdAt"], "time_created")},
                       {_column_select(columns, ["time_updated", "timeUpdated", "updated_at", "updatedAt"], "time_updated")},
                       {data} AS {_quote("data")}
                FROM {_quote("message")}
                {where}
                """
            )
    if _table_exists(connection, "part"):
        columns = _columns(connection, "part")
        data = opencode_schema.data_expr(columns)
        where, where_params = _session_filter(columns, session_ids)
        if where is not None:
            params.extend(where_params)
            branches.append(
                f"""
                SELECT 'part' AS source_table,
                       {_column_select(columns, ["id"], "id")},
                       {_column_select(columns, ["session_id", "sessionID"], "session_id")},
                       {_column_select(columns, ["message_id", "messageID"], "message_id")},
                       {opencode_schema.coalesce([opencode_schema.json_extract(data, "$.type"), "'part'"])} AS {_quote("event_type")},
                       {_column_select(columns, ["time_created", "timeCreated", "created_at", "createdAt"], "time_created")},
                       {_column_select(columns, ["time_updated", "timeUpdated", "updated_at", "updatedAt"], "time_updated")},
                       {data} AS {_quote("data")}
                FROM {_quote("part")}
                {where}
                """
            )
    if _table_exists(connection, "event"):
        columns = _columns(connection, "event")
        data = opencode_schema.data_expr(columns)
        where, where_params = _session_filter(
            columns,
            session_ids,
            session_expr=opencode_schema.event_session_id_expr(columns, data),
        )
        if where is not None:
            params.extend(where_params)
            branches.append(
                f"""
                SELECT 'event' AS source_table,
                       {_column_select(columns, ["id"], "id")},
                       {opencode_schema.event_session_id_expr(columns, data)} AS {_quote("session_id")},
                       CAST(NULL AS TEXT) AS message_id,
                       {opencode_schema.event_type_expr(columns, data)} AS {_quote("event_type")},
                       {opencode_schema.event_time_created_expr(columns, data)} AS {_quote("time_created")},
                       {_column_select(columns, ["time_updated", "timeUpdated", "updated_at", "updatedAt"], "time_updated")},
                       {data} AS {_quote("data")}
                FROM {_quote("event")}
                {where}
                """
            )
    if not branches:
        return None
    query = (
        "SELECT * FROM (" + "\nUNION ALL\n".join(branches) + ") ORDER BY time_created DESC, source_table DESC, id DESC"
    )
    return query, params


def _session_filter(
    columns: list[str],
    session_ids: set[str] | None,
    *,
    session_expr: str | None = None,
) -> tuple[str | None, list[str]]:
    if session_ids is None:
        return "", []
    if session_expr is None:
        session_column = _first_column(columns, ["session_id", "sessionID"])
        if session_column is None:
            return None, []
        session_expr = _quote(session_column)
    placeholders = ", ".join("?" for _ in session_ids)
    return f"WHERE CAST({session_expr} AS TEXT) IN ({placeholders})", sorted(session_ids)


def _column_select(columns: list[str], candidates: list[str], alias: str, default: str = "NULL") -> str:
    return opencode_schema.column_select(columns, candidates, alias, default)


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
