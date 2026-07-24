from enum import StrEnum

from pydantic import BaseModel, ConfigDict, RootModel

from ocint.daemon.models import GitHubLogin, MessageClassification


class TaskKind(StrEnum):
    INITIAL = "initial"
    FOLLOW_UP = "follow_up"


class TaskState(StrEnum):
    UNRESOLVED = "unresolved"
    ADDRESSED = "addressed"
    REJECTED = "rejected"
    ERRORED = "errored"
    SKIPPED = "skipped"


class TaskReason(StrEnum):
    OWNED_PULL_REQUEST_CLOSED = "owned pull request is closed or merged"


class Thread(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    source_id: str
    configured_repository: str = ""
    eligible: bool = False
    title: str | None = None


class ThreadMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    thread_id: int
    source_id: str
    actor: GitHubLogin
    classification: MessageClassification
    body: str
    source_created_at: str


class Task(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    thread_id: int
    kind: TaskKind
    state: TaskState
    predecessor_task_id: int
    reason: str


class Threads(RootModel[list[Thread]]):
    model_config = ConfigDict(frozen=True)


class ThreadMessages(RootModel[list[ThreadMessage]]):
    model_config = ConfigDict(frozen=True)


class SuccessorCreated(BaseModel):
    model_config = ConfigDict(frozen=True)

    task: Task


class SuccessorExisting(BaseModel):
    model_config = ConfigDict(frozen=True)

    task: Task


class SuccessorUnavailable(BaseModel):
    model_config = ConfigDict(frozen=True)


class FailedTaskRetry(BaseModel):
    model_config = ConfigDict(frozen=True)

    task: Task
    attempt: int


class RetryAttachment(StrEnum):
    ATTACHED = "attached"
    EXISTING = "existing"
    REJECTED = "rejected"


type FailedTaskClaim = SuccessorCreated | SuccessorExisting | SuccessorUnavailable | FailedTaskRetry
