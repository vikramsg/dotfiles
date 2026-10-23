import sqlite3

PATH_VALUE_KEYS = ("path", "file", "filePath", "filepath", "relativePath")
PATH_ARRAY_KEYS = ("files", "filePaths")


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
    return row is not None


def columns(connection: sqlite3.Connection, table: str) -> list[str]:
    rows = connection.execute(f"PRAGMA table_info({quote(table)})").fetchall()
    return [str(row["name"]) for row in rows]


def quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def column_expr(
    columns_: list[str], candidates: list[str], default: str = "NULL", *, table_alias: str | None = None
) -> str:
    column = first_column(columns_, candidates)
    if column is None:
        return default
    if table_alias is not None:
        return f"{quote(table_alias)}.{quote(column)}"
    return quote(column)


def column_select(
    columns_: list[str], candidates: list[str], alias: str, default: str = "NULL", *, table_alias: str | None = None
) -> str:
    return f"{column_expr(columns_, candidates, default, table_alias=table_alias)} AS {quote(alias)}"


def data_expr(columns_: list[str], *, table_alias: str | None = None) -> str:
    data = column_expr(columns_, ["data"], table_alias=table_alias)
    if data == "NULL":
        return "'{}'"
    return f"CASE WHEN json_valid({data}) THEN {data} ELSE '{{}}' END"


def session_workspace_expr(columns_: list[str], data: str, *, table_alias: str | None = None) -> str:
    return coalesce(
        [
            column_expr(columns_, ["directory"], table_alias=table_alias),
            column_expr(columns_, ["cwd"], table_alias=table_alias),
            column_expr(columns_, ["path"], table_alias=table_alias),
            json_extract(data, "$.directory"),
            json_extract(data, "$.workspace"),
            json_extract(data, "$.cwd"),
            json_extract(data, "$.path"),
        ]
    )


def json_tree_path_predicate(tree_alias: str = "tree") -> str:
    tree = quote(tree_alias)
    value_keys = ", ".join(sql_string_literal(key) for key in PATH_VALUE_KEYS)
    array_predicates = " OR ".join(
        f"{tree}.{quote('path')} LIKE {sql_string_literal(f'$%.{key}')}" for key in PATH_ARRAY_KEYS
    )
    return f"({tree}.{quote('key')} IN ({value_keys}) OR {array_predicates})"


def coalesce(expressions: list[str]) -> str:
    usable = [expression for expression in expressions if expression != "NULL"]
    if not usable:
        return "NULL"
    if len(usable) == 1:
        return usable[0]
    return "COALESCE(" + ", ".join(usable) + ")"


def first_column(columns_: list[str], candidates: list[str]) -> str | None:
    lookup = {column.lower(): column for column in columns_}
    for candidate in candidates:
        if candidate.lower() in lookup:
            return lookup[candidate.lower()]
    return None


def json_extract(data: str, path: str) -> str:
    return f"json_extract({data}, {sql_string_literal(path)})"


def sql_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
