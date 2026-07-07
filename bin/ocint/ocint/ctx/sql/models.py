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
    from_expression: str | None = None
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
                from_expression=(
                    '"ctx_source" LEFT JOIN "ctx_refresh_state" ON "ctx_refresh_state"."source_id" = "ctx_source"."id"'
                ),
                columns=(
                    _text_column("provider", source_expression='"ctx_source"."provider"'),
                    _text_column("source_type", source_expression='"ctx_source"."source_type"'),
                    _text_column("name", source_expression='"ctx_source"."name"'),
                    CtxSqlColumn(
                        name="path",
                        source_expression='"ctx_source"."source_path"',
                        storage_type=CtxSqlColumnType.TEXT,
                    ),
                    _integer_column("sessions", source_expression='"ctx_source"."sessions"'),
                    _integer_column("events", source_expression='"ctx_source"."events"'),
                    CtxSqlColumn(
                        name="imported_at",
                        source_expression='"ctx_refresh_state"."latest_success_completed_at"',
                        storage_type=CtxSqlColumnType.INTEGER,
                    ),
                ),
            ),
        )
    )


def stable_view_create_statements(config: CtxSqlConfig) -> tuple[str, ...]:
    return tuple(stable_view_create_statement(view) for view in config.stable_views)


def stable_view_create_statement(view: CtxSqlStableView) -> str:
    """Render the canonical CREATE VIEW statement for one stable ctx projection."""
    column_sql = ",\n       ".join(
        f"{column.source_expression} AS {_quote_identifier(column.name)}" for column in view.columns
    )
    from_sql = view.from_expression if view.from_expression is not None else _quote_identifier(view.source_table)
    return f"CREATE VIEW {_quote_identifier(view.name)} AS\nSELECT {column_sql}\nFROM {from_sql}"


def _text_column(name: str, *, source_expression: str | None = None) -> CtxSqlColumn:
    return CtxSqlColumn(name=name, source_expression=source_expression or name, storage_type=CtxSqlColumnType.TEXT)


def _integer_column(name: str, *, source_expression: str | None = None) -> CtxSqlColumn:
    return CtxSqlColumn(name=name, source_expression=source_expression or name, storage_type=CtxSqlColumnType.INTEGER)


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'
