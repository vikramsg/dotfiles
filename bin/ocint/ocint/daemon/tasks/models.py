from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class MessageDisposition(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    IGNORED = "ignored"


class MessageActorType(StrEnum):
    HUMAN = "human"
    AGENT = "agent"


class TaskKind(StrEnum):
    INITIAL = "initial"
    FOLLOW_UP = "follow_up"


class TaskState(StrEnum):
    UNRESOLVED = "unresolved"
    ADDRESSED = "addressed"
    REJECTED = "rejected"
    ERRORED = "errored"
    SKIPPED = "skipped"


class Thread(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    repository: str
    source: str
    source_thread_id: str
    actor: str
    eligible: bool
    execution_job_id: str
    title: str
    body: str


class ThreadMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    thread_id: int
    source_message_id: str
    actor: str
    actor_type: MessageActorType
    disposition: MessageDisposition
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
