from pathlib import Path
from typing import Protocol

from ocint.daemon.models import PromptObservation
from ocint.daemon.opencode.config import OpenCodeConfig, OpenCodeRuntimeConfig


class OpenCodeGateway(Protocol):
    server_url: str
    username: str
    password: str

    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def create(self, directory: Path, identity: str) -> str: ...
    async def observe_prompt(self, directory: Path, session_id: str, text: str) -> PromptObservation: ...
    async def prompt(self, directory: Path, session_id: str, text: str) -> None: ...
    async def wait_for_completion(self, directory: Path, session_id: str, text: str) -> None: ...


def create_opencode_client(config: OpenCodeRuntimeConfig) -> OpenCodeGateway:
    from ocint.daemon.opencode.service import OpenCodeClient

    return OpenCodeClient(config)


__all__ = ["OpenCodeConfig", "OpenCodeGateway", "OpenCodeRuntimeConfig", "create_opencode_client"]
