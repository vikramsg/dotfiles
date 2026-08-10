from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ConversationIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = Field(min_length=1)
    workspace: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    thread: str = Field(min_length=1)


class ConversationMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_event_id: str = Field(min_length=1)
    conversation_identity: ConversationIdentity
    message_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    text: str
    source_created_at: str = Field(min_length=1)
    source_order_at: int = Field(ge=0)


class MessageKind(StrEnum):
    ROOT = "root"
    REPLY = "reply"
    UNSUPPORTED = "unsupported"


class ActorKind(StrEnum):
    HUMAN = "human"
    BOT = "bot"


class AuthorizationDecision(StrEnum):
    AUTHORIZED = "authorized"
    UNAUTHORIZED = "unauthorized"


class EventDisposition(StrEnum):
    ACCEPTED = "accepted"
    AWAITING_ROOT = "awaiting_root"
    IGNORED = "ignored"
    DUPLICATE = "duplicate"
    IDENTITY_CONFLICT = "identity_conflict"
    EXPIRED = "expired"


class ConversationState(StrEnum):
    AWAITING_ROOT = "awaiting_root"
    ACTIVE = "active"
    EXPIRED = "expired"


class TurnState(StrEnum):
    RECEIVED = "received"
    SESSION_READY = "session_ready"
    PROMPT_INTENDED = "prompt_intended"
    PROMPT_SUBMITTED = "prompt_submitted"
    RESPONSE_READY = "response_ready"
    DELIVERING = "delivering"
    COMPLETED = "completed"
    FAILED = "failed"
    IGNORED = "ignored"


class DeliveryState(StrEnum):
    PENDING = "pending"
    INTENDED = "intended"
    DELIVERED = "delivered"


class PreparedMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    message: ConversationMessage
    kind: MessageKind
    decision: AuthorizationDecision
    managed_prompt: str


class IngestResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    disposition: EventDisposition
    conversation_id: int = 0
    turn_ids: tuple[int, ...] = ()


class Conversation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    identity: ConversationIdentity
    state: ConversationState
    opencode_session_id: str
    created_at: str
    updated_at: str


class Turn(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    event_id: str
    conversation_id: int
    source_order_at: int
    source_order_tiebreaker: str
    state: TurnState
    managed_prompt: str
    opencode_user_message_id: str
    assistant_message_id: str
    response_text: str
    error: str
    retry_count: int
    retry_not_before: str
    created_at: str
    updated_at: str


class Delivery(BaseModel):
    model_config = ConfigDict(frozen=True)

    turn_id: int
    chunk_index: int
    client_msg_id: str
    text: str
    state: DeliveryState
    provider_message_id: str
    retry_count: int
    retry_not_before: str
    created_at: str
    updated_at: str


class ResponseChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int
    count: int
    text: str
    payload: str


@dataclass(frozen=True, slots=True)
class OpenCodeSessionId:
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("OpenCode session ID must not be empty")


@dataclass(frozen=True, slots=True)
class OpenCodeUserMessageId:
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("OpenCode user message ID must not be empty")


@dataclass(frozen=True, slots=True)
class OpenCodeAssistantMessageId:
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("OpenCode assistant message ID must not be empty")


class OpenCodeSessionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace: str
    identity: str


class OpenCodePromptRequest(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    session_id: OpenCodeSessionId
    user_message_id: OpenCodeUserMessageId
    prompt: str


class PromptPresence(StrEnum):
    ABSENT = "absent"
    ACTIVE = "active"
    COMPLETE = "complete"
    INTERRUPTED = "interrupted"


class OpenCodePromptObservation(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    presence: PromptPresence
    assistant_message_id: OpenCodeAssistantMessageId | None = None
    text: str = ""


class OpenCodeCompletion(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    assistant_message_id: OpenCodeAssistantMessageId
    text: str


class DeliveryRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    identity: ConversationIdentity
    client_message_id: str
    text: str


class DeliveryReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_message_id: str


class DeliveryMissing(BaseModel):
    model_config = ConfigDict(frozen=True)


type DeliveryLookup = DeliveryReceipt | DeliveryMissing
