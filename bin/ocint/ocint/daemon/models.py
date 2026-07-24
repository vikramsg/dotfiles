from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict


class LogRotation(Protocol):
    @property
    def max_bytes(self) -> int: ...

    @property
    def backup_count(self) -> int: ...


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStage(StrEnum):
    EXECUTION = "execution"
    VALIDATION = "validation"
    COMMIT = "commit"
    PUSH = "push"
    PULL_REQUEST = "pull_request"
    COMPLETE = "complete"


class Job(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    idempotency_key: str
    actor: str
    repository: str
    prompt: str
    state: JobState
    stage: JobStage
    session_id: str
    server_url: str
    worktree_path: Path | None
    branch: str
    base_revision: str
    prompt_intended: bool
    prompt_submitted: bool
    commit_sha: str
    pushed: bool
    pull_request_url: str
    error: str
    created_at: str
    updated_at: str
