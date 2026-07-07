from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData()

ctx_source = Table(
    "ctx_source",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("provider", String, nullable=False),
    Column("source_type", String, nullable=False),
    Column("name", String, nullable=False),
    Column("source_path", Text, nullable=False),
    Column("sessions", Integer, nullable=False, default=0),
    Column("events", Integer, nullable=False, default=0),
    UniqueConstraint("provider", "source_type", "source_path", name="uq_ctx_source_identity"),
)

ctx_refresh_state = Table(
    "ctx_refresh_state",
    metadata,
    Column("source_id", Integer, ForeignKey("ctx_source.id", ondelete="CASCADE"), primary_key=True),
    Column("latest_attempt_started_at", BigInteger, nullable=True),
    Column("latest_attempt_completed_at", BigInteger, nullable=True),
    Column("latest_attempt_status", String, nullable=True),
    Column("latest_success_started_at", BigInteger, nullable=True),
    Column("latest_success_completed_at", BigInteger, nullable=True),
    Column("latest_success_checkpoint_payload", Text, nullable=True),
    Column("source_watermark_payload", Text, nullable=True),
    Column("latest_failed_at", BigInteger, nullable=True),
    Column("latest_error_message", Text, nullable=True),
)

ctx_session = Table(
    "ctx_session",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source_id", Integer, ForeignKey("ctx_source.id", ondelete="CASCADE"), nullable=False),
    Column("provider", String, nullable=False),
    Column("provider_session_id", String, nullable=False),
    Column("session_id", String, nullable=False),
    Column("parent_id", String, nullable=True),
    Column("title", Text, nullable=True),
    Column("workspace", Text, nullable=True),
    Column("time_created", BigInteger, nullable=True),
    Column("time_updated", BigInteger, nullable=True),
    Column("source_path", Text, nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("source_fingerprint", Text, nullable=False),
    UniqueConstraint("source_id", "provider_session_id", name="uq_ctx_session_source_native"),
)

ctx_event = Table(
    "ctx_event",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source_id", Integer, ForeignKey("ctx_source.id", ondelete="CASCADE"), nullable=False),
    Column("provider", String, nullable=False),
    Column("provider_session_id", String, nullable=True),
    Column("event_id", String, nullable=False),
    Column("source_table", String, nullable=False),
    Column("message_id", String, nullable=True),
    Column("event_type", String, nullable=False),
    Column("time_created", BigInteger, nullable=True),
    Column("time_updated", BigInteger, nullable=True),
    Column("source_path", Text, nullable=True),
    Column("full_text", Text, nullable=False),
    Column("search_text", Text, nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("citation", Text, nullable=False),
    Column("source_fingerprint", Text, nullable=False),
    UniqueConstraint("source_id", "source_table", "event_id", name="uq_ctx_event_source_native"),
)

ctx_file_touched = Table(
    "ctx_file_touched",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source_id", Integer, ForeignKey("ctx_source.id", ondelete="CASCADE"), nullable=False),
    Column("provider", String, nullable=False),
    Column("path", Text, nullable=False),
    Column("provider_session_id", String, nullable=True),
    Column("event_id", String, nullable=False),
    Column("source_table", String, nullable=False),
    UniqueConstraint("source_id", "source_table", "event_id", "path", name="uq_ctx_file_source_event_path"),
)

Index("ix_ctx_session_provider_session", ctx_session.c.provider_session_id)
Index("ix_ctx_session_parent", ctx_session.c.parent_id)
Index("ix_ctx_event_provider_session", ctx_event.c.provider_session_id)
Index("ix_ctx_event_event_id", ctx_event.c.event_id)
Index("ix_ctx_event_time", ctx_event.c.time_created)
Index("ix_ctx_file_path", ctx_file_touched.c.path)


def ctx_event_fts_name() -> str:
    return "ctx_event_fts"


def ctx_event_fts_columns() -> tuple[str, ...]:
    return ("search_text", "event_pk", "event_id", "source_table")


def ctx_event_fts_create_statement() -> str:
    columns = ", ".join(
        column if column == "search_text" else f"{column} UNINDEXED" for column in ctx_event_fts_columns()
    )
    return f"CREATE VIRTUAL TABLE {ctx_event_fts_name()} USING fts5({columns})"
