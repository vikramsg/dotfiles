from enum import StrEnum

from ocint.ctx.models import CtxModel


class CtxSqlColumnType(StrEnum):
    TEXT = "TEXT"
    INTEGER = "INTEGER"


class CtxSqlColumn(CtxModel):
    name: str
    source_expression: str
    storage_type: CtxSqlColumnType


class CtxSqlStableView(CtxModel):
    name: str
    source_table: str
    columns: tuple[CtxSqlColumn, ...]


class CtxSqlConfig(CtxModel):
    """Backend-independent public SQL contract exposed by `ocint ctx sql`."""

    stable_views: tuple[CtxSqlStableView, ...]


def default_ctx_sql_config() -> CtxSqlConfig:
    """Return the stable ctx SQL projection contract used by migrations and sandbox reads."""
    return CtxSqlConfig(
        stable_views=(
            CtxSqlStableView(
                name="ctx_sessions",
                source_table="ctx_session",
                columns=(
                    _text_column("provider"),
                    _text_column("provider_session_id"),
                    _text_column("session_id"),
                    _text_column("parent_id"),
                    _text_column("title"),
                    _text_column("workspace"),
                    _integer_column("time_created"),
                    _integer_column("time_updated"),
                ),
            ),
            CtxSqlStableView(
                name="ctx_events",
                source_table="ctx_event",
                columns=(
                    _text_column("provider"),
                    _text_column("provider_session_id"),
                    _text_column("event_id"),
                    _text_column("source_table"),
                    _text_column("event_type"),
                    _integer_column("time_created"),
                    CtxSqlColumn(
                        name="text",
                        source_expression="full_text",
                        storage_type=CtxSqlColumnType.TEXT,
                    ),
                    _text_column("source_path"),
                    _text_column("citation"),
                ),
            ),
            CtxSqlStableView(
                name="ctx_files_touched",
                source_table="ctx_file_touched",
                columns=(
                    _text_column("provider"),
                    _text_column("path"),
                    _text_column("provider_session_id"),
                    _text_column("event_id"),
                    _text_column("source_table"),
                ),
            ),
            CtxSqlStableView(
                name="ctx_sources",
                source_table="ctx_source",
                columns=(
                    _text_column("provider"),
                    _text_column("source_type"),
                    _text_column("name"),
                    CtxSqlColumn(
                        name="path",
                        source_expression="source_path",
                        storage_type=CtxSqlColumnType.TEXT,
                    ),
                    _integer_column("sessions"),
                    _integer_column("events"),
                    _integer_column("imported_at"),
                ),
            ),
        )
    )


def stable_view_create_statements(config: CtxSqlConfig) -> tuple[str, ...]:
    return tuple(_stable_view_create_statement(view) for view in config.stable_views)


def _stable_view_create_statement(view: CtxSqlStableView) -> str:
    column_sql = ",\n       ".join(
        f"{column.source_expression} AS {_quote_identifier(column.name)}" for column in view.columns
    )
    return f"CREATE VIEW {_quote_identifier(view.name)} AS\nSELECT {column_sql}\nFROM {_quote_identifier(view.source_table)}"


def _text_column(name: str) -> CtxSqlColumn:
    return CtxSqlColumn(name=name, source_expression=name, storage_type=CtxSqlColumnType.TEXT)


def _integer_column(name: str) -> CtxSqlColumn:
    return CtxSqlColumn(name=name, source_expression=name, storage_type=CtxSqlColumnType.INTEGER)


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'
