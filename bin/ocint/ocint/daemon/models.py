from collections.abc import AsyncIterator, Mapping
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

type JsonValue = str | int | bool | None | list[JsonValue] | Mapping[str, JsonValue]


class JobState(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    RUNNING = "running"
    VALIDATING = "validating"
    PUBLISHING = "publishing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStage(StrEnum):
    EXECUTION = "execution"
    VALIDATION = "validation"
    COMMIT = "commit"
    PUSH = "push"
    PULL_REQUEST = "pull_request"
    COMPLETE = "complete"


class WorkSource(StrEnum):
    MANUAL = "manual"
    GITHUB = "github"
    SLACK = "slack"
    WEB = "web"


class WorkRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    idempotency_key: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source: WorkSource
    delivery_adapter: str = Field(min_length=1)
    delivery_target: str = Field(min_length=1)
    source_metadata: Mapping[str, str] = Field(default_factory=dict)


class WorkUpdate(BaseModel):
    model_config = ConfigDict(frozen=True)

    conversation_id: str
    job_id: str
    status: JobState
    message: str
    session_id: str = ""
    artifact_url: str = ""


class RuntimeSession(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    status: str


class RuntimeEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_type: str
    session_id: str
    payload: str
    status: str = ""


class RuntimePart(BaseModel):
    model_config = ConfigDict(frozen=True)

    part_type: str
    text: str


class RuntimeMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    message_id: str
    role: str
    parts: list[RuntimePart]


class PromptObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    found: bool
    completed: bool


class Job(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    idempotency_key: str
    conversation_id: str
    actor: str
    repository: str
    prompt: str
    source: WorkSource
    delivery_adapter: str
    delivery_target: str
    parent_job_id: str
    workspace_owner_id: str
    state: JobState
    stage: JobStage
    priority: int
    attempt_count: int
    session_id: str
    worktree_path: Path | None
    branch: str
    base_revision: str
    prompt_intended: bool
    prompt_submitted: bool
    commit_sha: str
    pushed: bool
    pull_request_url: str
    cancel_requested: bool
    server_url: str
    error: str
    created_at: datetime
    updated_at: datetime


class Claim(BaseModel):
    model_config = ConfigDict(frozen=True)

    job: Job
    attempt_id: str
    lease_id: str


class Worktree(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: Path
    branch: str
    base_revision: str


class Artifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str
    value: str
    url: str


class PersistedEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    kind: str
    payload: str
    created_at: datetime


class OutboxItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    job_id: str
    source: WorkSource
    delivery_adapter: str
    delivery_target: str
    lease_id: str
    conversation_id: str
    update: WorkUpdate


class RecoveryPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: JobState
    stage: JobStage
    reset_execution: bool
    error: str


class Continuation(BaseModel):
    model_config = ConfigDict(frozen=True)

    parent_job_id: str
    workspace_owner_id: str
    session_id: str
    worktree_path: Path
    branch: str
    base_revision: str
    server_url: str


class WorkspaceRetirement(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace_owner_id: str
    worktree_path: Path
    lease_id: str
    disposed: bool
    removed: bool


class Channel(Protocol):
    source: WorkSource
    adapter_id: str

    async def run(self) -> None: ...

    def accepts(self, delivery_target: str) -> bool: ...

    async def publish(self, update: WorkUpdate, delivery_key: str, delivery_target: str) -> None: ...


class AgentRuntime(Protocol):
    async def start(self) -> None: ...

    async def health(self) -> None: ...

    async def close(self) -> None: ...

    async def create(self, directory: Path, identity: str) -> RuntimeSession: ...

    async def prompt(self, directory: Path, session_id: str, text: str) -> None: ...

    async def has_prompt(self, directory: Path, session_id: str, text: str) -> bool: ...

    async def prompt_observation(self, directory: Path, session_id: str, text: str) -> PromptObservation: ...

    async def messages(self, directory: Path, session_id: str) -> list[RuntimeMessage]: ...

    async def inspect(self, directory: Path, session_id: str) -> RuntimeSession: ...

    def events(self, directory: Path, session_id: str) -> AsyncIterator[RuntimeEvent]: ...

    async def cancel(self, directory: Path, session_id: str) -> None: ...

    async def dispose(self, directory: Path) -> None: ...
