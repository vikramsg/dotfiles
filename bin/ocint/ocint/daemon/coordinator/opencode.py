from collections.abc import Awaitable
from pathlib import Path
from typing import Protocol

from ocint.daemon.coordinator.contracts import RetryableCoordinatorError, TerminalCoordinatorError
from ocint.daemon.coordinator.models import (
    OpenCodeAssistantMessageId,
    OpenCodeCompletion,
    OpenCodePromptObservation,
    OpenCodePromptRequest,
    OpenCodeSessionId,
    OpenCodeSessionRequest,
    PromptPresence,
)
from ocint.daemon.models import PromptObservation
from ocint.daemon.opencode import (
    OpenCodePrompt,
    OpenCodeResponse,
    RetryableOpenCodeError,
    TerminalOpenCodeError,
)


class CorrelatedOpenCodeGateway(Protocol):
    async def create(self, directory: Path, identity: str) -> str: ...
    async def observe_response(self, directory: Path, session_id: str, prompt: OpenCodePrompt) -> PromptObservation: ...
    async def submit_prompt(self, directory: Path, session_id: str, prompt: OpenCodePrompt) -> None: ...
    async def wait_for_response(self, directory: Path, session_id: str, prompt: OpenCodePrompt) -> OpenCodeResponse: ...


class OpenCodeCoordinatorAdapter:
    def __init__(self, gateway: CorrelatedOpenCodeGateway, workspace: Path) -> None:
        self.gateway = gateway
        self.workspace = workspace.expanduser().resolve()

    async def create_or_reuse_session(self, request: OpenCodeSessionRequest) -> OpenCodeSessionId:
        requested_workspace = Path(request.workspace).expanduser().resolve()
        if requested_workspace != self.workspace:
            raise ValueError("coordinator OpenCode request used an unexpected workspace")
        return OpenCodeSessionId(await self._call(self.gateway.create(self.workspace, request.identity)))

    async def observe_prompt(self, request: OpenCodePromptRequest) -> OpenCodePromptObservation:
        prompt = self._prompt(request)
        observation = await self._call(self.gateway.observe_response(self.workspace, request.session_id.value, prompt))
        if not observation.found:
            return OpenCodePromptObservation(presence=PromptPresence.ABSENT)
        if observation.active:
            return OpenCodePromptObservation(presence=PromptPresence.ACTIVE)
        if not observation.completed:
            return OpenCodePromptObservation(presence=PromptPresence.INTERRUPTED)
        response = await self._call(self.gateway.wait_for_response(self.workspace, request.session_id.value, prompt))
        return OpenCodePromptObservation(
            presence=PromptPresence.COMPLETE,
            assistant_message_id=OpenCodeAssistantMessageId(response.assistant_message_id),
            text=response.text,
        )

    async def submit_prompt(self, request: OpenCodePromptRequest) -> None:
        await self._call(self.gateway.submit_prompt(self.workspace, request.session_id.value, self._prompt(request)))

    async def wait_for_completion(self, request: OpenCodePromptRequest) -> OpenCodeCompletion:
        response = await self._call(
            self.gateway.wait_for_response(
                self.workspace,
                request.session_id.value,
                self._prompt(request),
            )
        )
        if response.parent_message_id != request.user_message_id.value:
            raise RuntimeError("OpenCode assistant response parent did not match the managed user message")
        return OpenCodeCompletion(
            assistant_message_id=OpenCodeAssistantMessageId(response.assistant_message_id),
            text=response.text,
        )

    @staticmethod
    def _prompt(request: OpenCodePromptRequest) -> OpenCodePrompt:
        return OpenCodePrompt(message_id=request.user_message_id.value, text=request.prompt)

    @staticmethod
    async def _call[Result](operation: Awaitable[Result]) -> Result:
        try:
            return await operation
        except RetryableOpenCodeError as error:
            raise RetryableCoordinatorError(str(error)) from error
        except TerminalOpenCodeError as error:
            raise TerminalCoordinatorError(str(error)) from error
