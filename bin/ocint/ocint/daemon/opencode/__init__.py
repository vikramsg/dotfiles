from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from ocint.daemon.models import PromptObservation
from ocint.daemon.opencode.config import OpenCodeConfig, OpenCodeRuntimeConfig


class OpenCodePrompt(BaseModel):
    model_config = ConfigDict(frozen=True)

    message_id: str = Field(min_length=1)
    text: str


class OpenCodeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    assistant_message_id: str = Field(min_length=1)
    parent_message_id: str = Field(min_length=1)
    text: str


class OpenCodeAdapterError(RuntimeError):
    """An OpenCode failure classified at the provider boundary."""


class RetryableOpenCodeError(OpenCodeAdapterError):
    """A temporary OpenCode failure that may succeed on a later attempt."""


class TerminalOpenCodeError(OpenCodeAdapterError):
    """An OpenCode failure that must produce the coordinator's safe response."""


class OpenCodeGateway(Protocol):
    server_url: str
    username: str
    password: str

    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def wait_exited(self) -> int: ...
    async def create(self, directory: Path, identity: str) -> str: ...
    async def observe_prompt(self, directory: Path, session_id: str, text: str) -> PromptObservation: ...
    async def prompt(self, directory: Path, session_id: str, text: str) -> None: ...
    async def wait_for_completion(self, directory: Path, session_id: str, text: str) -> None: ...
    async def observe_response(self, directory: Path, session_id: str, prompt: OpenCodePrompt) -> PromptObservation: ...
    async def submit_prompt(self, directory: Path, session_id: str, prompt: OpenCodePrompt) -> None: ...
    async def wait_for_response(self, directory: Path, session_id: str, prompt: OpenCodePrompt) -> OpenCodeResponse: ...


def create_opencode_client(config: OpenCodeRuntimeConfig) -> OpenCodeGateway:
    from ocint.daemon.opencode.service import OpenCodeClient

    return OpenCodeClient(config)


__all__ = [
    "OpenCodeAdapterError",
    "OpenCodeConfig",
    "OpenCodeGateway",
    "OpenCodePrompt",
    "OpenCodeResponse",
    "OpenCodeRuntimeConfig",
    "RetryableOpenCodeError",
    "TerminalOpenCodeError",
    "create_opencode_client",
]
