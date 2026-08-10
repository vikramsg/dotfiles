from pathlib import Path

import pytest
from ocint.daemon.coordinator import (
    OpenCodeCoordinatorAdapter,
    OpenCodePromptRequest,
    OpenCodeSessionId,
    OpenCodeSessionRequest,
    OpenCodeUserMessageId,
    PromptPresence,
    RetryableCoordinatorError,
)
from ocint.daemon.models import PromptObservation
from ocint.daemon.opencode import OpenCodePrompt, OpenCodeResponse, RetryableOpenCodeError


class FakeOpenCodeGateway:
    def __init__(self, observation: PromptObservation) -> None:
        self.observation = observation
        self.submitted: OpenCodePrompt | None = None
        self.failure: RetryableOpenCodeError | None = None

    async def create(self, directory: Path, identity: str) -> str:
        assert directory.name == "workspace"
        assert identity == "conversation"
        return "session"

    async def observe_response(self, directory: Path, session_id: str, prompt: OpenCodePrompt) -> PromptObservation:
        assert directory.name == "workspace"
        assert session_id == "session"
        assert prompt.message_id == "msg_managed"
        if self.failure is not None:
            raise self.failure
        return self.observation

    async def submit_prompt(self, directory: Path, session_id: str, prompt: OpenCodePrompt) -> None:
        assert directory.name == "workspace"
        assert session_id == "session"
        self.submitted = prompt

    async def wait_for_response(self, directory: Path, session_id: str, prompt: OpenCodePrompt) -> OpenCodeResponse:
        assert directory.name == "workspace"
        assert session_id == "session"
        return OpenCodeResponse(
            assistant_message_id="assistant",
            parent_message_id=prompt.message_id,
            text="answer",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("observation", "presence"),
    [
        (PromptObservation(found=False, completed=False, active=False), PromptPresence.ABSENT),
        (PromptObservation(found=True, completed=False, active=True), PromptPresence.ACTIVE),
        (PromptObservation(found=True, completed=False, active=False), PromptPresence.INTERRUPTED),
        (PromptObservation(found=True, completed=True, active=False), PromptPresence.COMPLETE),
    ],
)
async def test_opencode_adapter_correlates_by_message_id_and_maps_prompt_state(
    tmp_path: Path, observation: PromptObservation, presence: PromptPresence
) -> None:
    # GIVEN
    gateway = FakeOpenCodeGateway(observation)
    adapter = OpenCodeCoordinatorAdapter(gateway, tmp_path / "workspace")
    request = OpenCodePromptRequest(
        session_id=OpenCodeSessionId("session"),
        user_message_id=OpenCodeUserMessageId("msg_managed"),
        prompt="managed prompt",
    )

    # WHEN
    session = await adapter.create_or_reuse_session(
        OpenCodeSessionRequest(workspace=str(tmp_path / "workspace"), identity="conversation")
    )
    observed = await adapter.observe_prompt(request)
    await adapter.submit_prompt(request)
    completion = await adapter.wait_for_completion(request)

    # THEN
    assert session == OpenCodeSessionId("session")
    assert observed.presence is presence
    assert gateway.submitted == OpenCodePrompt(message_id="msg_managed", text="managed prompt")
    assert completion.assistant_message_id.value == "assistant"
    assert completion.text == "answer"


@pytest.mark.asyncio
async def test_opencode_adapter_maps_retryable_provider_failure_to_coordinator_retry(tmp_path: Path) -> None:
    # GIVEN
    gateway = FakeOpenCodeGateway(PromptObservation(found=False, completed=False, active=False))
    gateway.failure = RetryableOpenCodeError("provider temporarily unavailable")
    adapter = OpenCodeCoordinatorAdapter(gateway, tmp_path / "workspace")
    request = OpenCodePromptRequest(
        session_id=OpenCodeSessionId("session"),
        user_message_id=OpenCodeUserMessageId("msg_managed"),
        prompt="managed prompt",
    )

    # WHEN / THEN
    with pytest.raises(RetryableCoordinatorError, match="provider temporarily unavailable"):
        await adapter.observe_prompt(request)
