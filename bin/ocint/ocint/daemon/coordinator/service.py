from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field

from ocint.daemon.coordinator.models import (
    ActorKind,
    AuthorizationDecision,
    ConversationIdentity,
    ConversationMessage,
    MessageKind,
    PreparedMessage,
    ResponseChunk,
)


class ChannelAccess(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = Field(min_length=1)
    workspace: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    authorized_actors: frozenset[str] = Field(min_length=1)


class AuthorizationPolicy(Protocol):
    def authorize(self, message: ConversationMessage, actor_kind: ActorKind) -> AuthorizationDecision: ...


class ConfiguredAuthorizationPolicy:
    def __init__(self, channels: tuple[ChannelAccess, ...]) -> None:
        self.channels = channels

    def authorize(self, message: ConversationMessage, actor_kind: ActorKind) -> AuthorizationDecision:
        if actor_kind is ActorKind.BOT:
            return AuthorizationDecision.UNAUTHORIZED
        identity = message.conversation_identity
        for channel in self.channels:
            if (
                channel.provider == identity.provider
                and channel.workspace == identity.workspace
                and channel.channel == identity.channel
            ):
                return (
                    AuthorizationDecision.AUTHORIZED
                    if message.actor_id in channel.authorized_actors
                    else AuthorizationDecision.UNAUTHORIZED
                )
        return AuthorizationDecision.UNAUTHORIZED


class CoordinatorService:
    def __init__(
        self, authorization: AuthorizationPolicy, response_chunk_characters: int, safe_failure_text: str
    ) -> None:
        if response_chunk_characters <= 16 or response_chunk_characters > 3_500:
            raise ValueError("response chunk size must be between 17 and 3500 characters")
        if not safe_failure_text:
            raise ValueError("safe failure text must not be empty")
        self.authorization = authorization
        self.response_chunk_characters = response_chunk_characters
        self.safe_failure_text = safe_failure_text

    def prepare(self, message: ConversationMessage, kind: MessageKind, actor_kind: ActorKind) -> PreparedMessage:
        decision = (
            AuthorizationDecision.UNAUTHORIZED
            if kind is MessageKind.UNSUPPORTED
            else self.authorization.authorize(message, actor_kind)
        )
        return PreparedMessage(
            message=message,
            kind=kind,
            decision=decision,
            managed_prompt=self.managed_prompt(message),
        )

    def managed_prompt(self, message: ConversationMessage) -> str:
        identity = message.conversation_identity
        return (
            "Coordinator turn\n"
            f"provider: {identity.provider}\n"
            f"workspace: {identity.workspace}\n"
            f"channel: {identity.channel}\n"
            f"thread: {identity.thread}\n"
            f"message: {message.message_id}\n"
            f"actor: {message.actor_id}\n\n"
            f"{message.text}"
        )

    def session_identity(self, identity: ConversationIdentity) -> str:
        value = ":".join((identity.provider, identity.workspace, identity.channel, identity.thread))
        return str(uuid5(NAMESPACE_URL, f"ocint-coordinator-conversation:{value}"))

    def chunks(self, response: str) -> tuple[ResponseChunk, ...]:
        expected_count = 1
        while True:
            payloads = self._split(response, expected_count)
            actual_count = len(payloads)
            if actual_count == expected_count:
                return tuple(
                    ResponseChunk(
                        index=index,
                        count=actual_count,
                        text=f"[{index}/{actual_count}] {payload}",
                        payload=payload,
                    )
                    for index, payload in enumerate(payloads, start=1)
                )
            expected_count = actual_count

    @staticmethod
    def reconstruct(chunks: tuple[ResponseChunk, ...]) -> str:
        return "".join(chunk.payload for chunk in chunks)

    def failure_chunks(self) -> tuple[ResponseChunk, ...]:
        return self.chunks(self.safe_failure_text)

    def _split(self, response: str, expected_count: int) -> tuple[str, ...]:
        if not response:
            return ("",)
        payloads: list[str] = []
        remaining = response
        while remaining:
            index = len(payloads) + 1
            prefix_length = len(f"[{index}/{expected_count}] ")
            capacity = self.response_chunk_characters - prefix_length
            if capacity <= 0:
                raise ValueError("response chunk size is too small for numbering")
            if len(remaining) <= capacity:
                payloads.append(remaining)
                break
            split_at = self._boundary(remaining, capacity)
            payloads.append(remaining[:split_at])
            remaining = remaining[split_at:]
        return tuple(payloads)

    @staticmethod
    def _boundary(text: str, capacity: int) -> int:
        window = text[:capacity]
        paragraph = window.rfind("\n\n")
        if paragraph >= 0:
            return paragraph + 2
        newline = window.rfind("\n")
        if newline >= 0:
            return newline + 1
        for index in range(len(window) - 1, -1, -1):
            if window[index].isspace():
                return index + 1
        return capacity
