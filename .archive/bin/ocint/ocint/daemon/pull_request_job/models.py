from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ocint.daemon.models import ActorIdentity, DirectOrigin, WorkOrigin


class PullRequestJobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class PullRequestJobStage(StrEnum):
    EXECUTION = "execution"
    VALIDATION = "validation"
    COMMIT = "commit"
    PUSH = "push"
    PULL_REQUEST = "pull_request"
    COMPLETE = "complete"


class PullRequestJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    idempotency_key: str = Field(min_length=1)
    actor: ActorIdentity
    repository: str = Field(min_length=1)
    title: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    origin: WorkOrigin = Field(default_factory=DirectOrigin)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        title = value.strip()
        summary = title[6:] if title.casefold().startswith("ocint:") else title
        summary = summary.strip()
        if not summary:
            raise ValueError("work title must contain text after the ocint prefix")
        return f"ocint: {summary}"


@dataclass(frozen=True)
class SourcePullRequestJobRequest:
    """Internal source-authorized request that is never an HTTP payload model."""

    work: PullRequestJobRequest


class PullRequestJob(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    idempotency_key: str
    actor: ActorIdentity
    repository: str
    title: str
    prompt: str
    state: PullRequestJobState
    stage: PullRequestJobStage
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


class WorktreeCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: Literal["worktree"] = "worktree"
    path: Path
    branch: str
    base_revision: str


class SessionCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: Literal["session"] = "session"
    session_id: str
    server_url: str


class PromptIntentCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: Literal["prompt_intent"] = "prompt_intent"


class PromptSubmittedCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: Literal["prompt_submitted"] = "prompt_submitted"


class StageCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: Literal["stage"] = "stage"
    stage: PullRequestJobStage


class CommitCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: Literal["commit"] = "commit"
    sha: str


class PushCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: Literal["push"] = "push"
    revision: str


class PullRequestCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: Literal["pull_request"] = "pull_request"
    url: str


class PublicationRefusalCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: Literal["publication_refusal"] = "publication_refusal"
    reason: str


type Checkpoint = (
    WorktreeCheckpoint
    | SessionCheckpoint
    | PromptIntentCheckpoint
    | PromptSubmittedCheckpoint
    | StageCheckpoint
    | CommitCheckpoint
    | PushCheckpoint
    | PullRequestCheckpoint
    | PublicationRefusalCheckpoint
)
