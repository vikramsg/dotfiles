import re
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator


class LogRotation(Protocol):
    @property
    def max_bytes(self) -> int: ...

    @property
    def backup_count(self) -> int: ...


class GitRepository(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    remote_url: str
    default_branch: str = "main"

    @field_validator("remote_url")
    @classmethod
    def validate_ssh_remote(cls, value: str) -> str:
        scp_style = re.fullmatch(r"[^@\s/:]+@[^\s/:]+:.+", value)
        ssh_url = re.fullmatch(r"ssh://(?:[^@/\s]+@)?[^/:\s]+(?::[0-9]+)?/.+", value)
        if scp_style is None and ssh_url is None:
            raise ValueError("repository remote_url must use SSH (git@host:path or ssh://host/path)")
        return value


class ActorIdentity(RootModel[str]):
    model_config = ConfigDict(frozen=True)

    @field_validator("root")
    @classmethod
    def normalize(cls, value: str) -> str:
        login = value.strip().casefold()
        if not login:
            raise ValueError("actor identity cannot be empty")
        return login

    def __str__(self) -> str:
        return self.root


class GitHubLogin(ActorIdentity):
    """Backward-compatible GitHub configuration identity."""


class MessageClassification(StrEnum):
    ACTIONABLE = "actionable"
    UNAUTHORIZED = "unauthorized"
    AGENT_RESPONSE = "agent_response"


class ObservedMessage(BaseModel):
    """Source message transferred to task coordination before persistence."""

    model_config = ConfigDict(frozen=True)

    source_id: str = Field(min_length=1)
    actor: ActorIdentity
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


class Worktree(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: Path
    branch: str
    base_revision: str


class PromptObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    found: bool
    completed: bool
    active: bool


class DirectOrigin(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["direct"] = "direct"


class ThreadOrigin(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["thread"] = "thread"
    source_thread_id: str = Field(min_length=1)
    source_anchor_id: str = Field(min_length=1)


type WorkOrigin = Annotated[DirectOrigin | ThreadOrigin, Field(discriminator="kind")]


class PublicationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    base: str = Field(min_length=1)
    title: str = Field(min_length=1)
    body: str
    origin: WorkOrigin
    owned_pull_request_number: int = 0


class PublishedPublication(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["published"] = "published"
    url: str = Field(min_length=1)
    number: int = Field(gt=0)


class RefusedPublication(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["refused"] = "refused"
    reason: Literal["owned_pull_request_closed"] = "owned_pull_request_closed"


type PublicationResult = Annotated[PublishedPublication | RefusedPublication, Field(discriminator="status")]


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


class OpenCodeAttachment(BaseModel):
    model_config = ConfigDict(frozen=True)

    server_url: str
    username: str
    password: str
    directory: str
    session_id: str
