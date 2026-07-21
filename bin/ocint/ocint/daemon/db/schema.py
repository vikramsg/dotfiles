from sqlalchemy import Column, ForeignKey, Index, Integer, MetaData, String, Table, Text, UniqueConstraint

metadata = MetaData()

job = Table(
    "job",
    metadata,
    Column("id", String, primary_key=True),
    Column("idempotency_key", String, nullable=False, unique=True),
    Column("actor", String, nullable=False),
    Column("repository", String, nullable=False),
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
    Column("outcome", String, nullable=False),
    Column("response", Text, nullable=False),
    Column("error", Text, nullable=False),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
)

Index("ix_job_queue", job.c.state, job.c.created_at)

thread = Table(
    "thread",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source_id", String, nullable=False, unique=True),
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
    Column("thread_id", Integer, ForeignKey("thread.id"), primary_key=True),
    Column("root_message_id", Integer, ForeignKey("thread_message.id"), nullable=False, unique=True),
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
    Column("github_comment_id", Integer, primary_key=True),
    Column("message_id", Integer, ForeignKey("thread_message.id"), nullable=False, unique=True),
    Column("marker", String, nullable=False),
)

Index("ix_thread_message_classification", thread_message.c.thread_id, thread_message.c.classification)
Index("ix_task_state", task.c.thread_id, task.c.state)
