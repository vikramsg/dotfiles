from sqlalchemy import Column, Index, Integer, MetaData, String, Table, Text

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
    Column("error", Text, nullable=False),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
)

Index("ix_job_queue", job.c.state, job.c.created_at)
