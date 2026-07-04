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
    Column("imported_at", BigInteger, nullable=False),
    Column("sessions", Integer, nullable=False, default=0),
    Column("events", Integer, nullable=False, default=0),
    Column("checkpoint_payload", Text, nullable=True),
    UniqueConstraint("provider", "source_type", "source_path", name="uq_ctx_source_identity"),
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

STABLE_CTX_VIEW_COLUMNS = {
    "ctx_sessions": (
        "provider",
        "provider_session_id",
        "session_id",
        "parent_id",
        "title",
        "workspace",
        "time_created",
        "time_updated",
    ),
    "ctx_events": (
        "provider",
        "provider_session_id",
        "event_id",
        "source_table",
        "event_type",
        "time_created",
        "text",
        "source_path",
        "citation",
    ),
    "ctx_files_touched": ("provider", "path", "provider_session_id", "event_id", "source_table"),
    "ctx_sources": ("provider", "source_type", "name", "path", "sessions", "events", "imported_at"),
}

STABLE_CTX_VIEWS = frozenset(STABLE_CTX_VIEW_COLUMNS)
