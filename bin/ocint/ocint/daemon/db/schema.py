from sqlalchemy import Column, ForeignKey, Index, Integer, MetaData, String, Table, Text, UniqueConstraint

metadata = MetaData()

job = Table(
    "job",
    metadata,
    Column("id", String, primary_key=True),
    Column("idempotency_key", String, nullable=False, unique=True),
    Column("actor", String, nullable=False),
    Column("repository", String, nullable=False),
    Column("title", Text, nullable=False),
    Column("prompt", Text, nullable=False),
    Column("state", String, nullable=False),
    Column("stage", String, nullable=False),
    Column("session_id", String, nullable=False),
    Column("server_url", Text, nullable=False),
    Column("worktree_path", Text, nullable=False),
    Column("branch", String, nullable=False),
    Column("base_revision", String, nullable=False),
    Column("prompt_intended", Integer, nullable=False),
    Column("prompt_submitted", Integer, nullable=False),
    Column("commit_sha", String, nullable=False),
    Column("pushed", Integer, nullable=False),
    Column("pull_request_url", Text, nullable=False),
    Column("error", Text, nullable=False),
    Column("origin_kind", String, nullable=False),
    Column("origin_source_thread_id", String, nullable=False),
    Column("origin_source_anchor_id", String, nullable=False),
    Column("publication_refusal", String, nullable=False),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
)

Index("ix_job_queue", job.c.state, job.c.created_at)

thread = Table(
    "thread",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source_id", String, nullable=False, unique=True),
    Column("configured_repository", String, nullable=False),
    Column("eligible", Integer, nullable=False),
    Column("title", Text),
)

thread_message = Table(
    "thread_message",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("thread_id", Integer, ForeignKey("thread.id"), nullable=False),
    Column("source_id", String, nullable=False, unique=True),
    Column("actor", String, nullable=False),
    Column("classification", String, nullable=False),
    Column("body", Text, nullable=False),
    Column("source_created_at", String, nullable=False),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
)

task = Table(
    "task",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("thread_id", Integer, ForeignKey("thread.id"), nullable=False),
    Column("kind", String, nullable=False),
    Column("state", String, nullable=False),
    Column("predecessor_task_id", Integer, nullable=False),
    Column("retry_claim_attempt", Integer, nullable=False),
    Column("reason", Text, nullable=False),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
)

task_message = Table(
    "task_message",
    metadata,
    Column("task_id", Integer, ForeignKey("task.id"), primary_key=True),
    Column("message_id", Integer, ForeignKey("thread_message.id"), primary_key=True),
)

task_job = Table(
    "task_job",
    metadata,
    Column("task_id", Integer, ForeignKey("task.id"), primary_key=True),
    Column("job_id", String, ForeignKey("job.id"), primary_key=True),
    Column("attempt", Integer, nullable=False),
    UniqueConstraint("job_id", name="uq_task_job_job"),
    UniqueConstraint("task_id", "attempt", name="uq_task_job_attempt"),
)

github_issue = Table(
    "github_issue",
    metadata,
    Column("source_id", String, primary_key=True),
    Column("root_source_id", String, nullable=False, unique=True),
    Column("configured_repository", String, nullable=False),
    Column("github_repository", String, nullable=False),
    Column("github_issue_id", Integer, nullable=False),
    Column("issue_number", Integer, nullable=False),
    Column("eligible", Integer, nullable=False),
    Column("pull_request_number", Integer, nullable=False),
    Column("pull_request_url", Text, nullable=False),
    UniqueConstraint("github_repository", "github_issue_id", name="uq_github_issue_identity"),
)

github_issue_comment = Table(
    "github_issue_comment",
    metadata,
    Column("source_id", String, primary_key=True),
    Column("issue_source_id", String, ForeignKey("github_issue.source_id"), nullable=False),
    Column("github_comment_id", Integer, nullable=False, unique=True),
    Column("marker", String, nullable=False),
)

pull_request_ownership = Table(
    "pull_request_ownership",
    metadata,
    Column("source_thread_id", String, primary_key=True),
    Column("repository", String, primary_key=True),
    Column("number", Integer, nullable=False),
    Column("url", Text, nullable=False),
)

slack_channel = Table(
    "slack_channel",
    metadata,
    Column("channel_id", String, primary_key=True),
    Column("watermark", String, nullable=False),
    Column("retry_not_before", String, nullable=False),
)

slack_thread = Table(
    "slack_thread",
    metadata,
    Column("channel_id", String, primary_key=True),
    Column("root_ts", String, primary_key=True),
    Column("workspace_id", String, nullable=False),
    Column("logical_source_id", String, nullable=False),
    Column("root_identity", Text, nullable=False, unique=True),
    Column("configured_repository", String, nullable=False),
    Column("title", Text, nullable=False),
    Column("authorized", Integer, nullable=False),
    Column("closed", Integer, nullable=False),
    Column("reopen_root", Integer, nullable=False),
)

slack_message = Table(
    "slack_message",
    metadata,
    Column("channel_id", String, primary_key=True),
    Column("ts", String, primary_key=True),
    Column("root_ts", String, nullable=False),
    Column("user_id", String, nullable=False),
    Column("body", Text, nullable=False),
    Column("classification", String, nullable=False),
)

slack_reply = Table(
    "slack_reply",
    metadata,
    Column("idempotency_key", String, primary_key=True),
    Column("channel_id", String, nullable=False),
    Column("ts", String, nullable=False),
)

coordinator_event = Table(
    "coordinator_event",
    metadata,
    Column("event_id", String, primary_key=True),
    Column("provider", String, nullable=False),
    Column("workspace_id", String, nullable=False),
    Column("channel_id", String, nullable=False),
    Column("thread_id", String, nullable=False),
    Column("message_id", String, nullable=False),
    Column("actor_id", String, nullable=False),
    Column("text", Text, nullable=False),
    Column("source_created_at", String, nullable=False),
    Column("source_order_at", Integer, nullable=False),
    Column("message_kind", String, nullable=False),
    Column("managed_prompt", Text, nullable=False),
    Column("disposition", String, nullable=False),
    Column("created_at", String, nullable=False),
    UniqueConstraint(
        "provider",
        "workspace_id",
        "channel_id",
        "thread_id",
        "message_id",
        name="uq_coordinator_event_message",
    ),
)

coordinator_conversation = Table(
    "coordinator_conversation",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("provider", String, nullable=False),
    Column("workspace_id", String, nullable=False),
    Column("channel_id", String, nullable=False),
    Column("thread_id", String, nullable=False),
    Column("state", String, nullable=False),
    Column("opencode_session_id", String, nullable=False),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
    UniqueConstraint(
        "provider", "workspace_id", "channel_id", "thread_id", name="uq_coordinator_conversation_identity"
    ),
)

coordinator_turn = Table(
    "coordinator_turn",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("event_id", String, ForeignKey("coordinator_event.event_id"), nullable=False, unique=True),
    Column("conversation_id", Integer, ForeignKey("coordinator_conversation.id"), nullable=False),
    Column("source_order_at", Integer, nullable=False),
    Column("source_order_tiebreaker", String, nullable=False),
    Column("state", String, nullable=False),
    Column("managed_prompt", Text, nullable=False),
    Column("opencode_user_message_id", String, nullable=False, unique=True),
    Column("assistant_message_id", String, nullable=False),
    Column("response_text", Text, nullable=False),
    Column("error", Text, nullable=False),
    Column("retry_count", Integer, nullable=False),
    Column("retry_not_before", String, nullable=False),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
)

coordinator_delivery = Table(
    "coordinator_delivery",
    metadata,
    Column("turn_id", Integer, ForeignKey("coordinator_turn.id"), primary_key=True),
    Column("chunk_index", Integer, primary_key=True),
    Column("client_msg_id", String, nullable=False, unique=True),
    Column("text", Text, nullable=False),
    Column("state", String, nullable=False),
    Column("provider_message_id", String, nullable=False),
    Column("retry_count", Integer, nullable=False),
    Column("retry_not_before", String, nullable=False),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
)

Index(
    "ix_coordinator_event_conversation",
    coordinator_event.c.provider,
    coordinator_event.c.workspace_id,
    coordinator_event.c.channel_id,
    coordinator_event.c.thread_id,
)
Index(
    "ix_coordinator_turn_ready",
    coordinator_turn.c.state,
    coordinator_turn.c.retry_not_before,
    coordinator_turn.c.source_order_at,
    coordinator_turn.c.source_order_tiebreaker,
)
Index("ix_coordinator_delivery_ready", coordinator_delivery.c.state, coordinator_delivery.c.retry_not_before)

Index("ix_thread_message_classification", thread_message.c.thread_id, thread_message.c.classification)
Index("ix_task_state", task.c.thread_id, task.c.state)
