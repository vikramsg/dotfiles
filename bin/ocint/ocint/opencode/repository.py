import hashlib
import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from ocint._db import inspect_schema, open_readonly_connection
from ocint._sqlsafe import execute_readonly_query
from ocint.opencode import schema as opencode_schema
from ocint.opencode.models import (
    OpenCodeDetailedAgentUsage,
    OpenCodeDetailedProjectAgentUsage,
    OpenCodeDetailedProjectUsage,
    OpenCodeDetailedUsageResult,
    OpenCodeDetailedUsageTokens,
    OpenCodeJsonModel,
    OpenCodeMessageData,
    OpenCodeMessageRow,
    OpenCodePartData,
    OpenCodePartRow,
    OpenCodeSessionData,
    OpenCodeSessionKey,
    OpenCodeSessionMessageKey,
    OpenCodeSessionRow,
    OpenCodeTranscriptEventKey,
    OpenCodeTranscriptEventRow,
    OpenCodeUsageSession,
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
            rows = connection.execute(_sessions_sql(connection)).fetchall()
            return [_session_from_row(row) for row in rows]

    def session_keys(self) -> list[OpenCodeSessionKey]:
        with self.readonly_connection() as connection:
            if not _table_exists(connection, "session"):
                return []
            rows = connection.execute(_sessions_sql(connection)).fetchall()
            return [OpenCodeSessionKey(id=str(row["id"]), fingerprint=_fingerprint_row(row)) for row in rows]

    def sessions_for_ids(self, ids: Sequence[str]) -> list[OpenCodeSessionRow]:
        unique_ids = list(dict.fromkeys(ids))
        if not unique_ids:
            return []
        with self.readonly_connection() as connection:
            if not _table_exists(connection, "session"):
                return []
            placeholders = ", ".join("?" for _ in unique_ids)
            rows = connection.execute(
                f"{_sessions_sql(connection)} WHERE {_quote('id')} IN ({placeholders})",
                tuple(unique_ids),
            ).fetchall()
            return [_session_from_row(row) for row in rows]

    def messages(self) -> list[OpenCodeMessageRow]:
        with self.readonly_connection() as connection:
            return self._messages(connection)

    def parts(self) -> list[OpenCodePartRow]:
        with self.readonly_connection() as connection:
            return self._parts(connection)

    def usage_sessions(self, *, start_ms: int | None) -> list[OpenCodeUsageSession]:
        with self.readonly_connection() as connection:
            required_session = {
                "id",
                "time_created",
                "time_updated",
                "cost",
                "tokens_input",
                "tokens_output",
                "tokens_reasoning",
                "tokens_cache_read",
                "tokens_cache_write",
            }
            required_message = {"id", "session_id"}
            _require_columns(connection, "session", required_session)
            _require_columns(connection, "message", required_message)
            where = "WHERE session.time_updated >= ?" if start_ms is not None else ""
            params = (start_ms,) if start_ms is not None else ()
            rows = connection.execute(
                f"""
                SELECT session.id, session.time_created, session.time_updated,
                       COUNT(message.id) AS messages, session.cost,
                       session.tokens_input, session.tokens_output,
                       session.tokens_reasoning, session.tokens_cache_read,
                       session.tokens_cache_write
                FROM session
                LEFT JOIN message ON message.session_id = session.id
                {where}
                GROUP BY session.id
                ORDER BY session.time_updated DESC, session.id DESC
                """,
                params,
            ).fetchall()
            return [OpenCodeUsageSession.model_validate(dict(row)) for row in rows]

    def detailed_usage(self, *, start_ms: int | None) -> OpenCodeDetailedUsageResult:
        """Load current-schema assistant message aggregates for state detailed."""
        with self.readonly_connection() as connection:
            connection.execute("BEGIN")
            try:
                _require_columns(connection, "message", {"id", "session_id", "time_created", "data"})
                _require_columns(connection, "session", {"id", "project_id", "parent_id", "time_updated", "cost"})
                _require_columns(connection, "project", {"id", "worktree"})
                time_filter = "AND message.time_created >= ?" if start_ms is not None else ""
                session_time_filter = "WHERE session.time_updated >= ?" if start_ms is not None else ""
                params = (start_ms, start_ms) if start_ms is not None else ()
                rows = connection.execute(
                    f"""
                    WITH assistant_message AS MATERIALIZED (
                      SELECT
                        message.id AS message_id,
                        message.session_id,
                        session.project_id,
                        project.worktree,
                        json_extract(message.data, '$.agent') AS agent,
                        json_type(message.data, '$.agent') AS agent_type,
                        trim(json_extract(message.data, '$.agent'), char(9) || char(10) || char(11) || char(12) || char(13) || ' ')
                          AS agent_trimmed,
                        CASE WHEN session.parent_id IS NULL THEN 'root' ELSE 'subagent' END AS kind,
                        json_type(message.data, '$.cost') AS cost_type,
                        json_type(message.data, '$.tokens.input') AS tokens_input_type,
                        json_type(message.data, '$.tokens.output') AS tokens_output_type,
                        json_type(message.data, '$.tokens.reasoning') AS tokens_reasoning_type,
                        json_type(message.data, '$.tokens.cache.read') AS tokens_cache_read_type,
                        json_type(message.data, '$.tokens.cache.write') AS tokens_cache_write_type,
                        CAST(json_extract(message.data, '$.cost') AS REAL) AS cost,
                        CAST(json_extract(message.data, '$.tokens.input') AS INTEGER) AS tokens_input,
                        CAST(json_extract(message.data, '$.tokens.output') AS INTEGER) AS tokens_output,
                        CAST(json_extract(message.data, '$.tokens.reasoning') AS INTEGER) AS tokens_reasoning,
                        CAST(json_extract(message.data, '$.tokens.cache.read') AS INTEGER) AS tokens_cache_read,
                        CAST(json_extract(message.data, '$.tokens.cache.write') AS INTEGER) AS tokens_cache_write
                      FROM message
                      JOIN session ON session.id = message.session_id
                      LEFT JOIN project ON project.id = session.project_id
                      WHERE json_extract(message.data, '$.role') = 'assistant'
                      {time_filter}
                    ),
                    invalid_assistant_message AS (
                      SELECT
                        message_id,
                        CASE
                          WHEN agent_type IS NOT 'text' OR agent_trimmed = '' THEN 'historical agent identity'
                          ELSE 'required usage data'
                        END AS invalid_reason
                      FROM assistant_message
                      WHERE agent_type IS NOT 'text'
                         OR agent_trimmed = ''
                         OR (cost_type IS NOT 'integer' AND cost_type IS NOT 'real')
                         OR (tokens_input_type IS NOT 'integer' AND tokens_input_type IS NOT 'real')
                         OR (tokens_output_type IS NOT 'integer' AND tokens_output_type IS NOT 'real')
                         OR (tokens_reasoning_type IS NOT 'integer' AND tokens_reasoning_type IS NOT 'real')
                         OR (tokens_cache_read_type IS NOT 'integer' AND tokens_cache_read_type IS NOT 'real')
                         OR (tokens_cache_write_type IS NOT 'integer' AND tokens_cache_write_type IS NOT 'real')
                      ORDER BY message_id
                      LIMIT 1
                    ),
                    session_total AS (
                      SELECT COALESCE(SUM(session.cost), 0.0) AS cost
                      FROM session
                      {session_time_filter}
                    )
                    SELECT
                      'invalid' AS section,
                      0 AS section_order,
                      message_id,
                      invalid_reason,
                      NULL AS project_id,
                      NULL AS worktree,
                      NULL AS agent,
                      NULL AS kind,
                      NULL AS sessions,
                      NULL AS assistant_messages,
                      NULL AS cost,
                      NULL AS tokens_input,
                      NULL AS tokens_output,
                      NULL AS tokens_reasoning,
                      NULL AS tokens_cache_read,
                      NULL AS tokens_cache_write
                    FROM invalid_assistant_message
                    UNION ALL
                    SELECT
                      'opencode_total' AS section,
                      1 AS section_order,
                      NULL AS message_id,
                      NULL AS invalid_reason,
                      NULL AS project_id,
                      NULL AS worktree,
                      NULL AS agent,
                      NULL AS kind,
                      NULL AS sessions,
                      NULL AS assistant_messages,
                      cost,
                      NULL AS tokens_input,
                      NULL AS tokens_output,
                      NULL AS tokens_reasoning,
                      NULL AS tokens_cache_read,
                      NULL AS tokens_cache_write
                    FROM session_total
                    UNION ALL
                    SELECT
                      'project' AS section,
                      2 AS section_order,
                      NULL AS message_id,
                      NULL AS invalid_reason,
                      project_id,
                      worktree,
                      NULL AS agent,
                      NULL AS kind,
                      COUNT(DISTINCT session_id) AS sessions,
                      COUNT(*) AS assistant_messages,
                      SUM(cost) AS cost,
                      SUM(tokens_input) AS tokens_input,
                      SUM(tokens_output) AS tokens_output,
                      SUM(tokens_reasoning) AS tokens_reasoning,
                      SUM(tokens_cache_read) AS tokens_cache_read,
                      SUM(tokens_cache_write) AS tokens_cache_write
                    FROM assistant_message
                    WHERE NOT EXISTS (SELECT 1 FROM invalid_assistant_message)
                    GROUP BY project_id, worktree
                    UNION ALL
                    SELECT
                      'agent' AS section,
                      3 AS section_order,
                      NULL AS message_id,
                      NULL AS invalid_reason,
                      NULL AS project_id,
                      NULL AS worktree,
                      agent,
                      kind,
                      COUNT(DISTINCT session_id) AS sessions,
                      COUNT(*) AS assistant_messages,
                      SUM(cost) AS cost,
                      SUM(tokens_input) AS tokens_input,
                      SUM(tokens_output) AS tokens_output,
                      SUM(tokens_reasoning) AS tokens_reasoning,
                      SUM(tokens_cache_read) AS tokens_cache_read,
                      SUM(tokens_cache_write) AS tokens_cache_write
                    FROM assistant_message
                    WHERE NOT EXISTS (SELECT 1 FROM invalid_assistant_message)
                    GROUP BY agent, kind
                    UNION ALL
                    SELECT
                      'project_agent' AS section,
                      4 AS section_order,
                      NULL AS message_id,
                      NULL AS invalid_reason,
                      project_id,
                      worktree,
                      agent,
                      kind,
                      COUNT(DISTINCT session_id) AS sessions,
                      COUNT(*) AS assistant_messages,
                      SUM(cost) AS cost,
                      SUM(tokens_input) AS tokens_input,
                      SUM(tokens_output) AS tokens_output,
                      SUM(tokens_reasoning) AS tokens_reasoning,
                      SUM(tokens_cache_read) AS tokens_cache_read,
                      SUM(tokens_cache_write) AS tokens_cache_write
                    FROM assistant_message
                    WHERE NOT EXISTS (SELECT 1 FROM invalid_assistant_message)
                    GROUP BY project_id, worktree, agent, kind
                    ORDER BY section_order, cost DESC, worktree, project_id, agent, kind
                    """,
                    params,
                ).fetchall()
            finally:
                connection.rollback()
        return _detailed_usage_result(rows)

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

    def transcript_event_keys(self) -> list[OpenCodeTranscriptEventKey]:
        with self.readonly_connection() as connection:
            sql = _transcript_events_sql(connection)
            if sql is None:
                return []
            rows = connection.execute(sql).fetchall()
            return [_transcript_event_key_from_row(row) for row in rows]

    def transcript_event_batches_for_keys(
        self,
        keys: Sequence[tuple[str, str]],
        batch_size: int,
    ) -> Iterator[list[OpenCodeTranscriptEventRow]]:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        unique_keys = list(dict.fromkeys(keys))
        if not unique_keys:
            return
        with self.readonly_connection() as connection:
            sql = _transcript_events_sql(connection)
            if sql is None:
                return
            for chunk in _chunks(unique_keys, max(1, min(batch_size, 500))):
                predicate = " OR ".join("(source_table = ? AND id = ?)" for _source_table, _id in chunk)
                params: list[str] = []
                for source_table, event_id in chunk:
                    params.extend([source_table, event_id])
                cursor = connection.execute(f"SELECT * FROM ({sql}) WHERE {predicate}", tuple(params))
                while rows := cursor.fetchmany(batch_size):
                    yield [_transcript_event_from_row(row) for row in rows]

    def session_message_keys(self) -> list[OpenCodeSessionMessageKey]:
        with self.readonly_connection() as connection:
            if not _table_exists(connection, "session_message"):
                return []
            columns = _columns(connection, "session_message")
            session_col = _first_column(columns, ["session_id", "sessionID"])
            message_col = _first_column(columns, ["message_id", "messageID"])
            if session_col is None or message_col is None:
                return []
            rows = connection.execute(
                f"""
                SELECT {_quote(session_col)} AS session_id,
                       {_quote(message_col)} AS message_id
                FROM {_quote("session_message")}
                ORDER BY session_id, message_id
                """
            ).fetchall()
            return [
                OpenCodeSessionMessageKey(
                    session_id=str(row["session_id"]),
                    message_id=str(row["message_id"]),
                    fingerprint=_fingerprint_row(row),
                )
                for row in rows
                if row["session_id"] is not None and row["message_id"] is not None
            ]

    def source_table_watermarks(self) -> dict[str, dict[str, int | None]]:
        with self.readonly_connection() as connection:
            return {
                table: _source_table_watermark(connection, table)
                for table in ["session", "message", "part", "session_message"]
            }

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


def _sessions_sql(connection: sqlite3.Connection) -> str:
    columns = _columns(connection, "session")
    data = opencode_schema.data_expr(columns)
    return f"""
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


def _transcript_event_key_from_row(row: sqlite3.Row) -> OpenCodeTranscriptEventKey:
    source_table = str(row["source_table"])
    source_table_literal: Literal["message", "part"]
    if source_table == "message":
        source_table_literal = "message"
    elif source_table == "part":
        source_table_literal = "part"
    else:
        raise ValueError(f"Unsupported OpenCode transcript source table: {source_table}")
    return OpenCodeTranscriptEventKey(
        id=str(row["id"]),
        source_table=source_table_literal,
        session_id=_optional_str(row["session_id"]),
        message_id=_optional_str(row["message_id"]),
        fingerprint=_fingerprint_row(row),
    )


def _table_count(connection: sqlite3.Connection, table: str) -> int:
    if not _table_exists(connection, table):
        return 0
    return int(connection.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()[0] or 0)


def _source_table_watermark(connection: sqlite3.Connection, table: str) -> dict[str, int | None]:
    if not _table_exists(connection, table):
        return {"rows": 0, "max_time_created": None, "max_time_updated": None}
    columns = _columns(connection, table)
    time_created = opencode_schema.column_expr(columns, ["time_created", "timeCreated", "created_at", "createdAt"])
    time_updated = opencode_schema.column_expr(columns, ["time_updated", "timeUpdated", "updated_at", "updatedAt"])
    created_expr = time_created if time_created != "NULL" else "NULL"
    updated_expr = time_updated if time_updated != "NULL" else "NULL"
    row = connection.execute(
        f"""
        SELECT COUNT(*) AS rows,
               MAX({created_expr}) AS max_time_created,
               MAX({updated_expr}) AS max_time_updated
        FROM {_quote(table)}
        """
    ).fetchone()
    return {
        "rows": int(row["rows"] or 0),
        "max_time_created": _optional_int(row["max_time_created"]),
        "max_time_updated": _optional_int(row["max_time_updated"]),
    }


def _fingerprint_row(row: sqlite3.Row) -> str:
    payload = dict(row)
    payload.pop("sort_time", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _chunks[T](items: Sequence[T], size: int) -> Iterator[list[T]]:
    for index in range(0, len(items), size):
        yield list(items[index : index + size])


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


def _require_columns(connection: sqlite3.Connection, table: str, required: set[str]) -> None:
    if not _table_exists(connection, table):
        raise ValueError(f"OpenCode database is missing required table: {table}")
    missing = sorted(required - set(_columns(connection, table)))
    if missing:
        raise ValueError(f"OpenCode {table} table is missing required columns: {', '.join(missing)}")


def _detailed_usage_result(rows: list[sqlite3.Row]) -> OpenCodeDetailedUsageResult:
    opencode_total_cost = 0.0
    projects: list[OpenCodeDetailedProjectUsage] = []
    agents: list[OpenCodeDetailedAgentUsage] = []
    project_agents: list[OpenCodeDetailedProjectAgentUsage] = []
    for row in rows:
        section = row["section"]
        if section == "invalid":
            raise ValueError(f"OpenCode assistant message has invalid {row['invalid_reason']}: {row['message_id']}")
        if section == "opencode_total":
            opencode_total_cost = float(row["cost"])
            continue
        if section == "project":
            projects.append(
                OpenCodeDetailedProjectUsage(
                    project_id=row["project_id"],
                    worktree=row["worktree"],
                    sessions=int(row["sessions"]),
                    assistant_messages=int(row["assistant_messages"]),
                    cost=float(row["cost"]),
                    tokens=_detailed_usage_tokens(row),
                )
            )
            continue
        if section == "agent":
            agents.append(
                OpenCodeDetailedAgentUsage(
                    agent=row["agent"],
                    kind=row["kind"],
                    sessions=int(row["sessions"]),
                    assistant_messages=int(row["assistant_messages"]),
                    cost=float(row["cost"]),
                    tokens=_detailed_usage_tokens(row),
                )
            )
            continue
        if section == "project_agent":
            project_agents.append(
                OpenCodeDetailedProjectAgentUsage(
                    project_id=row["project_id"],
                    worktree=row["worktree"],
                    agent=row["agent"],
                    kind=row["kind"],
                    sessions=int(row["sessions"]),
                    assistant_messages=int(row["assistant_messages"]),
                    cost=float(row["cost"]),
                    tokens=_detailed_usage_tokens(row),
                )
            )
            continue
        raise ValueError(f"OpenCode detailed usage returned unknown section: {section}")
    return OpenCodeDetailedUsageResult(
        opencode_total_cost=opencode_total_cost,
        projects=projects,
        agents=agents,
        project_agents=project_agents,
    )


def _detailed_usage_tokens(row: sqlite3.Row) -> OpenCodeDetailedUsageTokens:
    tokens_input = int(row["tokens_input"])
    tokens_output = int(row["tokens_output"])
    tokens_reasoning = int(row["tokens_reasoning"])
    tokens_cache_read = int(row["tokens_cache_read"])
    tokens_cache_write = int(row["tokens_cache_write"])
    return OpenCodeDetailedUsageTokens(
        input=tokens_input,
        output=tokens_output,
        reasoning=tokens_reasoning,
        cache_read=tokens_cache_read,
        cache_write=tokens_cache_write,
        total=tokens_input + tokens_output + tokens_reasoning + tokens_cache_read + tokens_cache_write,
    )


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
