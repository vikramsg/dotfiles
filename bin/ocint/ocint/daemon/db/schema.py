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
    Column("error", Text, nullable=False),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
)

Index("ix_job_queue", job.c.state, job.c.created_at)

github_issue = Table(
    "github_issue",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("repository", String, nullable=False),
    Column("github_repository", String, nullable=False),
    Column("github_issue_id", Integer, nullable=False),
    Column("issue_number", Integer, nullable=False),
    Column("issue_author", String, nullable=False),
    Column("title", Text, nullable=False),
    Column("body", Text, nullable=False),
    Column("job_id", String, ForeignKey("job.id"), nullable=False, unique=True),
    Column("pull_request_number", Integer, nullable=False),
    Column("pull_request_url", Text, nullable=False),
    Column("initial_state", String, nullable=False),
    Column("active_anchor_comment_id", Integer, nullable=False),
    Column("error", Text, nullable=False),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
    UniqueConstraint("repository", "github_issue_id", name="uq_github_issue_repository_issue"),
)

github_issue_comment = Table(
    "github_issue_comment",
    metadata,
    Column("github_comment_id", Integer, primary_key=True),
    Column("issue_id", Integer, ForeignKey("github_issue.id"), nullable=False),
    Column("body", Text, nullable=False),
    Column("actor_login", String, nullable=False),
    Column("actor_type", String, nullable=False),
    Column("state", String, nullable=False),
    Column("github_created_at", String, nullable=False),
    Column("marker", String, nullable=False),
    Column("agent_response_comment_id", Integer, nullable=False),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
)

Index("ix_github_issue_comment_pending", github_issue_comment.c.issue_id, github_issue_comment.c.state)
