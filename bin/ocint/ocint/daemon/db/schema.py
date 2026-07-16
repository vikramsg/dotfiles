from sqlalchemy import Column, ForeignKey, Index, Integer, MetaData, String, Table, Text, UniqueConstraint

metadata = MetaData()

source_event = Table(
    "source_event",
    metadata,
    Column("id", String, primary_key=True),
    Column("idempotency_key", String, nullable=False, unique=True),
    Column("source", String, nullable=False),
    Column("payload", Text, nullable=False),
    Column("created_at", String, nullable=False),
)

job = Table(
    "job",
    metadata,
    Column("id", String, primary_key=True),
    Column("source_event_id", String, ForeignKey("source_event.id"), nullable=False, unique=True),
    Column("idempotency_key", String, nullable=False, unique=True),
    Column("conversation_id", String, nullable=False),
    Column("actor", String, nullable=False),
    Column("repository", String, nullable=False),
    Column("prompt", Text, nullable=False),
    Column("source", String, nullable=False),
    Column("delivery_adapter", String, nullable=False),
    Column("delivery_target", String, nullable=False),
    Column("parent_job_id", String, ForeignKey("job.id"), nullable=True),
    Column("workspace_owner_id", String, nullable=False),
    Column("state", String, nullable=False),
    Column("stage", String, nullable=False),
    Column("priority", Integer, nullable=False),
    Column("attempt_count", Integer, nullable=False),
    Column("session_id", String, nullable=False),
    Column("worktree_path", Text, nullable=False),
    Column("branch", String, nullable=False),
    Column("base_revision", String, nullable=False),
    Column("prompt_intended", Integer, nullable=False),
    Column("prompt_submitted", Integer, nullable=False),
    Column("commit_sha", String, nullable=False),
    Column("pushed", Integer, nullable=False),
    Column("pull_request_url", Text, nullable=False),
    Column("cancel_requested", Integer, nullable=False),
    Column("server_url", Text, nullable=False),
    Column("error", Text, nullable=False),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
)

attempt = Table(
    "attempt",
    metadata,
    Column("id", String, primary_key=True),
    Column("job_id", String, ForeignKey("job.id"), nullable=False),
    Column("number", Integer, nullable=False),
    Column("state", String, nullable=False),
    Column("config_snapshot", Text, nullable=False),
    Column("started_at", String, nullable=False),
    Column("finished_at", String, nullable=False),
    Column("error", Text, nullable=False),
    UniqueConstraint("job_id", "number"),
)

lease = Table(
    "lease",
    metadata,
    Column("id", String, primary_key=True),
    Column("job_id", String, ForeignKey("job.id"), nullable=False),
    Column("attempt_id", String, ForeignKey("attempt.id"), nullable=False),
    Column("owner", String, nullable=False),
    Column("acquired_at", String, nullable=False),
    Column("heartbeat_at", String, nullable=False),
    Column("expires_at", String, nullable=False),
    Column("released_at", String, nullable=False),
)

event = Table(
    "event",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("job_id", String, ForeignKey("job.id"), nullable=False),
    Column("attempt_id", String, ForeignKey("attempt.id"), nullable=True),
    Column("kind", String, nullable=False),
    Column("payload", Text, nullable=False),
    Column("created_at", String, nullable=False),
)

artifact = Table(
    "artifact",
    metadata,
    Column("id", String, primary_key=True),
    Column("job_id", String, ForeignKey("job.id"), nullable=False),
    Column("kind", String, nullable=False),
    Column("value", Text, nullable=False),
    Column("url", Text, nullable=False),
    Column("created_at", String, nullable=False),
    UniqueConstraint("job_id", "kind"),
)

outbox = Table(
    "outbox",
    metadata,
    Column("id", String, primary_key=True),
    Column("job_id", String, ForeignKey("job.id"), nullable=False),
    Column("source", String, nullable=False),
    Column("delivery_adapter", String, nullable=False),
    Column("conversation_id", String, nullable=False),
    Column("delivery_target", String, nullable=False),
    Column("payload", Text, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("available_at", String, nullable=False),
    Column("delivered_at", String, nullable=False),
    Column("last_error", Text, nullable=False),
    Column("lease_id", String, nullable=False),
    Column("lease_owner", String, nullable=False),
    Column("lease_expires_at", String, nullable=False),
)

workspace = Table(
    "workspace",
    metadata,
    Column("id", String, primary_key=True),
    Column("worktree_path", Text, nullable=False),
    Column("state", String, nullable=False),
    Column("lease_id", String, nullable=False),
    Column("lease_owner", String, nullable=False),
    Column("lease_expires_at", String, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("disposed", Integer, nullable=False),
    Column("removed", Integer, nullable=False),
    Column("last_error", Text, nullable=False),
    Column("updated_at", String, nullable=False),
)

runner = Table(
    "runner",
    metadata,
    Column("id", String, primary_key=True),
    Column("started_at", String, nullable=False),
    Column("heartbeat_at", String, nullable=False),
    Column("expires_at", String, nullable=False),
    Column("stopped_at", String, nullable=False),
)

Index("ix_job_queue", job.c.state, job.c.priority, job.c.created_at)
Index("ix_lease_active", lease.c.released_at, lease.c.expires_at)
Index("ix_event_job", event.c.job_id, event.c.id)
Index("ix_outbox_pending", outbox.c.delivered_at, outbox.c.available_at)
