from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator


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


class GitHubLogin(RootModel[str]):
    model_config = ConfigDict(frozen=True)

    @field_validator("root")
    @classmethod
    def normalize(cls, value: str) -> str:
        login = value.strip().casefold()
        if not login:
            raise ValueError("GitHub login cannot be empty")
        return login

    def __str__(self) -> str:
        return self.root


class MessageClassification(StrEnum):
    ACTIONABLE = "actionable"
    UNAUTHORIZED = "unauthorized"
    AGENT_RESPONSE = "agent_response"


class ObservedMessage(BaseModel):
    """Source message transferred to task coordination before persistence."""

    model_config = ConfigDict(frozen=True)

    source_id: str = Field(min_length=1)
    actor: GitHubLogin
    classification: MessageClassification
    body: str
    source_created_at: str = Field(min_length=1)


class ObservedMessages(RootModel[list[ObservedMessage]]):
    model_config = ConfigDict(frozen=True)


class ThreadObservation(BaseModel):
    """Complete source thread transferred to task coordination before persistence."""

    model_config = ConfigDict(frozen=True)

    source_id: str = Field(min_length=1)
    configured_repository: str = Field(min_length=1)
    title: str
    eligible: bool
    messages: ObservedMessages


class ThreadObservations(RootModel[list[ThreadObservation]]):
    model_config = ConfigDict(frozen=True)


class DirectOrigin(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["direct"] = "direct"


class ThreadOrigin(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["thread"] = "thread"
    source_thread_id: str = Field(min_length=1)
    source_anchor_id: str = Field(min_length=1)


type WorkOrigin = Annotated[DirectOrigin | ThreadOrigin, Field(discriminator="kind")]


class WorkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    idempotency_key: str = Field(min_length=1)
    actor: GitHubLogin
    repository: str = Field(min_length=1)
    title: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    origin: WorkOrigin = Field(default_factory=DirectOrigin)


class ReplyOutcome(StrEnum):
    ADDRESSED = "addressed"
    UNAUTHORIZED = "unauthorized"
    CLOSED_PULL_REQUEST = "closed-pr"


class ReplyRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_thread_id: str = Field(min_length=1)
    source_anchor_id: str = Field(min_length=1)
    outcome: ReplyOutcome
    text: str = Field(min_length=1)


class PublicationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    base: str = Field(min_length=1)
    title: str = Field(min_length=1)
    body: str
    origin: WorkOrigin


class PublishedPublication(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["published"] = "published"
    url: str = Field(min_length=1)


class RefusedPublication(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["refused"] = "refused"
    reason: Literal["owned_pull_request_closed"] = "owned_pull_request_closed"


type PublicationResult = Annotated[PublishedPublication | RefusedPublication, Field(discriminator="status")]


class Job(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    idempotency_key: str
    actor: GitHubLogin
    repository: str
    title: str
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
    origin: WorkOrigin = Field(default_factory=DirectOrigin)
    publication_refusal: str = ""
    created_at: str
    updated_at: str
