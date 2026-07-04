import sqlite3

from ocint.opencode import schema as opencode_schema


def install_ctx_views(connection: sqlite3.Connection) -> None:
    # The ctx views are TEMP objects on this read-only connection. They provide a
    # stable SQL API without creating, migrating, or refreshing OpenCode tables.
    for view in ["ctx_sources", "ctx_files_touched", "ctx_events", "ctx_sessions"]:
        connection.execute(f"DROP VIEW IF EXISTS {view}")
    connection.execute(_ctx_sessions_sql(connection))
    connection.execute(_ctx_events_sql(connection))
    connection.execute(_ctx_files_touched_sql(connection))
    connection.execute(_ctx_sources_sql())


def _ctx_sessions_sql(connection: sqlite3.Connection) -> str:
    if not _table_exists(connection, "session"):
        return _empty_view(
            "ctx_sessions",
            [
                "provider",
                "provider_session_id",
                "session_id",
                "parent_id",
                "title",
                "workspace",
                "time_created",
                "time_updated",
            ],
        )
    columns = _columns(connection, "session")
    base = "session_base"
    data = _data_expr(columns, table_alias=base)
    workspace = opencode_schema.session_workspace_expr(columns, data, table_alias=base)
    return f"""
    CREATE TEMP VIEW ctx_sessions AS
    SELECT
      'opencode' AS provider,
      CAST({_column_expr(columns, ["id"], "NULL", table_alias=base)} AS TEXT) AS provider_session_id,
      CAST({_column_expr(columns, ["id"], "NULL", table_alias=base)} AS TEXT) AS session_id,
      CAST({_column_expr(columns, ["parent_id", "parentID"], "NULL", table_alias=base)} AS TEXT) AS parent_id,
      CAST({_coalesce([_column_expr(columns, ["title"], table_alias=base), opencode_schema.json_extract(data, "$.title")])} AS TEXT) AS title,
      CAST({workspace} AS TEXT) AS workspace,
      CAST({_column_expr(columns, ["time_created", "timeCreated", "created_at", "createdAt"], "NULL", table_alias=base)} AS INTEGER) AS time_created,
      CAST({_column_expr(columns, ["time_updated", "timeUpdated", "updated_at", "updatedAt"], "NULL", table_alias=base)} AS INTEGER) AS time_updated
    FROM "session" AS {_quote(base)}
    """


def _ctx_events_sql(connection: sqlite3.Connection) -> str:
    branches: list[str] = []
    if _table_exists(connection, "event"):
        columns = _columns(connection, "event")
        base = "event_base"
        data = _data_expr(columns, table_alias=base)
        branches.append(
            f"""
            SELECT 'opencode' AS provider,
                   CAST({opencode_schema.event_session_id_expr(columns, data, table_alias=base)} AS TEXT) AS provider_session_id,
                   CAST({_column_expr(columns, ["id"], "NULL", table_alias=base)} AS TEXT) AS event_id,
                   'event' AS source_table,
                   CAST({opencode_schema.event_type_expr(columns, data, table_alias=base)} AS TEXT) AS event_type,
                   CAST({opencode_schema.event_time_created_expr(columns, data, table_alias=base)} AS INTEGER) AS time_created,
                   CAST({_coalesce([opencode_schema.json_extract(data, "$.text"), opencode_schema.json_extract(data, "$.message"), opencode_schema.json_extract(data, "$.title"), data])} AS TEXT) AS text
            FROM "event" AS {_quote(base)}
            """
        )
    if _table_exists(connection, "part"):
        columns = _columns(connection, "part")
        base = "part_base"
        data = _data_expr(columns, table_alias=base)
        branches.append(
            f"""
            SELECT 'opencode' AS provider,
                   CAST({_column_expr(columns, ["session_id", "sessionID"], "NULL", table_alias=base)} AS TEXT) AS provider_session_id,
                   CAST({_column_expr(columns, ["id"], "NULL", table_alias=base)} AS TEXT) AS event_id,
                   'part' AS source_table,
                   CAST({_coalesce([opencode_schema.json_extract(data, "$.type"), "'part'"])} AS TEXT) AS event_type,
                   CAST({_column_expr(columns, ["time_created", "timeCreated", "created_at", "createdAt"], "NULL", table_alias=base)} AS INTEGER) AS time_created,
                   CAST({_coalesce([opencode_schema.json_extract(data, "$.text"), opencode_schema.json_extract(data, "$.content"), data])} AS TEXT) AS text
            FROM "part" AS {_quote(base)}
            """
        )
    if _table_exists(connection, "message"):
        columns = _columns(connection, "message")
        base = "message_base"
        data = _data_expr(columns, table_alias=base)
        branches.append(
            f"""
            SELECT 'opencode' AS provider,
                   CAST({_column_expr(columns, ["session_id", "sessionID"], "NULL", table_alias=base)} AS TEXT) AS provider_session_id,
                   CAST({_column_expr(columns, ["id"], "NULL", table_alias=base)} AS TEXT) AS event_id,
                   'message' AS source_table,
                   CAST({_coalesce([opencode_schema.json_extract(data, "$.role"), "'message'"])} AS TEXT) AS event_type,
                   CAST({_column_expr(columns, ["time_created", "timeCreated", "created_at", "createdAt"], "NULL", table_alias=base)} AS INTEGER) AS time_created,
                   CAST({_coalesce([opencode_schema.json_extract(data, "$.text"), opencode_schema.json_extract(data, "$.content"), data])} AS TEXT) AS text
            FROM "message" AS {_quote(base)}
            """
        )
    if not branches:
        return _empty_view(
            "ctx_events",
            ["provider", "provider_session_id", "event_id", "source_table", "event_type", "time_created", "text"],
        )
    return "CREATE TEMP VIEW ctx_events AS\n" + "\nUNION ALL\n".join(branches)


def _ctx_files_touched_sql(connection: sqlite3.Connection) -> str:
    branches: list[str] = []
    for table in ["event", "part", "message"]:
        if not _table_exists(connection, table):
            continue
        columns = _columns(connection, table)
        base = f"{table}_file_base"
        data = _data_expr(columns, table_alias=base)
        session_expr = (
            opencode_schema.event_session_id_expr(columns, data, table_alias=base)
            if table == "event"
            else _column_expr(columns, ["session_id", "sessionID"], "NULL", table_alias=base)
        )
        branches.append(
            f"""
            SELECT DISTINCT
                   'opencode' AS provider,
                   CAST("tree"."value" AS TEXT) AS path,
                   CAST({session_expr} AS TEXT) AS provider_session_id,
                   CAST({_column_expr(columns, ["id"], "NULL", table_alias=base)} AS TEXT) AS event_id,
                   '{table}' AS source_table
            FROM {_quote(table)} AS {_quote(base)}, json_tree({data}) AS "tree"
            WHERE "tree"."type" = 'text'
              AND {opencode_schema.json_tree_path_predicate("tree")}
              AND CAST("tree"."value" AS TEXT) != ''
            """
        )
    if not branches:
        return _empty_view(
            "ctx_files_touched",
            ["provider", "path", "provider_session_id", "event_id", "source_table"],
        )
    return "CREATE TEMP VIEW ctx_files_touched AS\n" + "\nUNION ALL\n".join(branches)


def _ctx_sources_sql() -> str:
    return """
    CREATE TEMP VIEW ctx_sources AS
    SELECT 'opencode' AS provider,
           'sqlite' AS source_type,
           'main' AS name,
           NULL AS path,
           (SELECT COUNT(*) FROM ctx_sessions) AS sessions,
           (SELECT COUNT(*) FROM ctx_events) AS events
    """


def _empty_view(name: str, columns: list[str]) -> str:
    select = ", ".join(f"CAST(NULL AS TEXT) AS {_quote(column)}" for column in columns)
    return f"CREATE TEMP VIEW {name} AS SELECT {select} WHERE 0"


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return opencode_schema.table_exists(connection, table)


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return opencode_schema.columns(connection, table)


def _column_expr(
    columns: list[str],
    candidates: list[str],
    default: str = "NULL",
    *,
    table_alias: str | None = None,
) -> str:
    return opencode_schema.column_expr(columns, candidates, default, table_alias=table_alias)


def _data_expr(columns: list[str], *, table_alias: str | None = None) -> str:
    return opencode_schema.data_expr(columns, table_alias=table_alias)


def _coalesce(expressions: list[str]) -> str:
    return opencode_schema.coalesce(expressions)


def _quote(identifier: str) -> str:
    return opencode_schema.quote(identifier)
