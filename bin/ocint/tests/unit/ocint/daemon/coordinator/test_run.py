import asyncio
import signal
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from ocint.daemon.coordinator import (
    CoordinatorApplicationRequest,
    CoordinatorRuntime,
    OpenCodeCoordinatorAdapter,
    OpenCodePromptRequest,
    OpenCodeSessionId,
    OpenCodeSessionRequest,
    OpenCodeUserMessageId,
    ProcessSignalRegistrar,
    PromptPresence,
    RetryableCoordinatorError,
    RuntimeFileLock,
    open_coordinator_application,
    run_coordinator_application,
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


class LifecycleRuntime(CoordinatorRuntime):
    def __init__(self, events: list[str]) -> None:
        self.stops: list[asyncio.Event] = []
        self.events = events
        self.unexpected_exit = asyncio.Event()

    async def run(self, stop: asyncio.Event) -> None:
        self.stops.append(stop)
        stop_wait = asyncio.create_task(stop.wait())
        unexpected_wait = asyncio.create_task(self.unexpected_exit.wait())
        done, pending = await asyncio.wait((stop_wait, unexpected_wait), return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if unexpected_wait in done:
            self.events.append("worker exited")
            return
        self.events.append("worker stopped")

    def exit_unexpectedly(self) -> None:
        self.unexpected_exit.set()


class LifecycleOpenCode:
    def __init__(self, events: list[str], *, block_start: bool = False, start_failure: Exception | None = None) -> None:
        self.events = events
        self.exit_status = 0
        self.started = False
        self.closed = False
        self.exited = asyncio.Event()
        self.startup_started = asyncio.Event()
        self.allow_start = asyncio.Event()
        self.start_cancelled = False
        self.start_failure = start_failure
        if not block_start:
            self.allow_start.set()

    async def start(self) -> None:
        self.startup_started.set()
        try:
            await self.allow_start.wait()
        except asyncio.CancelledError:
            self.start_cancelled = True
            raise
        if self.start_failure is not None:
            raise self.start_failure
        self.started = True

    async def close(self) -> None:
        self.closed = True
        self.events.append("OpenCode closed")

    async def wait_exited(self) -> int:
        await self.exited.wait()
        return self.exit_status

    def exit_unexpectedly(self, status: int) -> None:
        self.exit_status = status
        self.exited.set()


class LifecycleSignalRegistrar:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.requests: list[Callable[[], None]] = []

    @contextmanager
    def register(self, request_shutdown: Callable[[], None]) -> Iterator[None]:
        self.events.append("signals registered")
        self.requests.append(request_shutdown)
        try:
            yield
        finally:
            self.requests.pop()
            self.events.append("signals restored")

    def request_shutdown(self) -> None:
        assert len(self.requests) == 1
        self.requests[0]()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("completed_component", "expected_error"),
    [
        ("worker", "coordinator application stopped unexpectedly"),
        ("ingress", "coordinator application stopped unexpectedly"),
        ("child", r"OpenCode exited unexpectedly \(47\)"),
    ],
)
async def test_unexpected_completion_precedes_an_already_requested_shutdown(
    tmp_path: Path, completed_component: str, expected_error: str
) -> None:
    # GIVEN
    events: list[str] = []
    runtime = LifecycleRuntime(events)
    opencode = LifecycleOpenCode(events)
    signals = LifecycleSignalRegistrar(events)
    ingress_exit = asyncio.Event()

    async def serve(shutdown: asyncio.Event) -> None:
        shutdown_wait = asyncio.create_task(shutdown.wait())
        unexpected_wait = asyncio.create_task(ingress_exit.wait())
        done, pending = await asyncio.wait((shutdown_wait, unexpected_wait), return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if unexpected_wait in done:
            events.append("ingress exited")

    request = CoordinatorApplicationRequest(
        runtime=runtime,
        opencode=opencode,
        ingress=serve,
        ingress_host="127.0.0.1",
        ingress_port=8_733,
        runtime_lock=tmp_path / "coordinator.lock",
        shutdown_timeout_seconds=1,
        signal_registrar=signals,
    )

    # WHEN
    async with open_coordinator_application(request) as application:
        if completed_component == "worker":
            runtime.exit_unexpectedly()
            completed_task = application.worker
        elif completed_component == "ingress":
            ingress_exit.set()
            completed_task = application.ingress
        else:
            opencode.exit_unexpectedly(47)
            completed_task = application.child
        async with asyncio.timeout(1):
            while not completed_task.done():
                await asyncio.sleep(0)
        application.request_shutdown()

        # THEN
        with pytest.raises(RuntimeError, match=expected_error):
            await application.wait()


@pytest.mark.asyncio
async def test_shutdown_during_blocking_start_cancels_and_closes_opencode_and_restores_signals(tmp_path: Path) -> None:
    # GIVEN
    events: list[str] = []
    runtime = LifecycleRuntime(events)
    opencode = LifecycleOpenCode(events, block_start=True)
    signals = LifecycleSignalRegistrar(events)

    async def serve(shutdown: asyncio.Event) -> None:
        await shutdown.wait()

    request = CoordinatorApplicationRequest(
        runtime=runtime,
        opencode=opencode,
        ingress=serve,
        ingress_host="127.0.0.1",
        ingress_port=8_733,
        runtime_lock=tmp_path / "coordinator.lock",
        shutdown_timeout_seconds=1,
        signal_registrar=signals,
    )

    opening = asyncio.create_task(run_coordinator_application(request))
    await asyncio.wait_for(opencode.startup_started.wait(), 1)
    async with asyncio.timeout(1):
        while not signals.requests:
            await asyncio.sleep(0)

    # WHEN
    signals.request_shutdown()
    await asyncio.wait_for(opening, 1)

    # THEN
    assert opencode.start_cancelled
    assert opencode.closed
    assert runtime.stops == []
    assert events[0] == "signals registered"
    assert events[-1] == "signals restored"
    assert signals.requests == []


@pytest.mark.asyncio
async def test_startup_failure_closes_opencode_remains_an_error_and_restores_signals(tmp_path: Path) -> None:
    # GIVEN
    events: list[str] = []
    runtime = LifecycleRuntime(events)
    opencode = LifecycleOpenCode(events, start_failure=RuntimeError("startup failed"))
    signals = LifecycleSignalRegistrar(events)

    async def serve(shutdown: asyncio.Event) -> None:
        await shutdown.wait()

    request = CoordinatorApplicationRequest(
        runtime=runtime,
        opencode=opencode,
        ingress=serve,
        ingress_host="127.0.0.1",
        ingress_port=8_733,
        runtime_lock=tmp_path / "coordinator.lock",
        shutdown_timeout_seconds=1,
        signal_registrar=signals,
    )

    # WHEN / THEN
    with pytest.raises(RuntimeError, match="startup failed"):
        async with open_coordinator_application(request):
            raise AssertionError("application started after OpenCode startup failed")
    assert opencode.closed
    assert runtime.stops == []
    assert events[0] == "signals registered"
    assert events[-1] == "signals restored"


def test_runtime_lock_is_private_persistent_and_rejects_a_second_worker(tmp_path: Path) -> None:
    # GIVEN
    path = tmp_path / "state" / "coordinator.lock"

    # WHEN
    with (
        RuntimeFileLock(path),
        pytest.raises(RuntimeError, match="another coordinator runtime"),
        RuntimeFileLock(path),
    ):
        raise AssertionError("a second coordinator unexpectedly acquired the runtime lock")

    # THEN
    assert path.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


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


@pytest.mark.asyncio
async def test_application_lifecycle_owns_start_supervision_and_bounded_shutdown(tmp_path: Path) -> None:
    # GIVEN
    events: list[str] = []
    runtime = LifecycleRuntime(events)
    opencode = LifecycleOpenCode(events)
    signals = LifecycleSignalRegistrar(events)
    ingress_stops: list[asyncio.Event] = []

    async def serve(shutdown: asyncio.Event) -> None:
        ingress_stops.append(shutdown)
        await shutdown.wait()
        events.append("ingress stopped")

    request = CoordinatorApplicationRequest(
        runtime=runtime,
        opencode=opencode,
        ingress=serve,
        ingress_host="127.0.0.1",
        ingress_port=8_733,
        runtime_lock=tmp_path / "coordinator.lock",
        shutdown_timeout_seconds=1,
        signal_registrar=signals,
    )

    # WHEN
    async with open_coordinator_application(request) as application:
        opencode.exit_unexpectedly(23)
        with pytest.raises(RuntimeError, match=r"OpenCode exited unexpectedly \(23\)"):
            await application.wait()

    # THEN
    assert opencode.started
    assert opencode.closed
    assert runtime.stops[0].is_set()
    assert ingress_stops[0].is_set()


@pytest.mark.asyncio
async def test_requested_shutdown_returns_normally_and_closes_bounded_work_before_opencode(tmp_path: Path) -> None:
    # GIVEN
    events: list[str] = []
    runtime = LifecycleRuntime(events)
    opencode = LifecycleOpenCode(events)
    signals = LifecycleSignalRegistrar(events)

    async def serve(shutdown: asyncio.Event) -> None:
        await shutdown.wait()
        events.append("ingress stopped")

    request = CoordinatorApplicationRequest(
        runtime=runtime,
        opencode=opencode,
        ingress=serve,
        ingress_host="127.0.0.1",
        ingress_port=8_733,
        runtime_lock=tmp_path / "coordinator.lock",
        shutdown_timeout_seconds=1,
        signal_registrar=signals,
    )

    # WHEN
    async with open_coordinator_application(request) as application:
        application.request_shutdown()
        await application.wait()
        events.append("wait returned")

    # THEN
    assert events.index("wait returned") < events.index("worker stopped")
    assert events.index("wait returned") < events.index("ingress stopped")
    assert events.index("worker stopped") < events.index("OpenCode closed")
    assert events.index("ingress stopped") < events.index("OpenCode closed")


@pytest.mark.asyncio
async def test_application_registers_shutdown_signals_and_restores_registration(tmp_path: Path) -> None:
    # GIVEN
    events: list[str] = []
    runtime = LifecycleRuntime(events)
    opencode = LifecycleOpenCode(events)
    signals = LifecycleSignalRegistrar(events)

    async def serve(shutdown: asyncio.Event) -> None:
        await shutdown.wait()

    request = CoordinatorApplicationRequest(
        runtime=runtime,
        opencode=opencode,
        ingress=serve,
        ingress_host="127.0.0.1",
        ingress_port=8_733,
        runtime_lock=tmp_path / "coordinator.lock",
        shutdown_timeout_seconds=1,
        signal_registrar=signals,
    )

    # WHEN
    async with open_coordinator_application(request) as application:
        signals.request_shutdown()
        await application.wait()

    # THEN
    assert events[0] == "signals registered"
    assert events[-1] == "signals restored"
    assert signals.requests == []


def test_process_signal_registrar_restores_prior_handlers() -> None:
    # GIVEN
    registrar = ProcessSignalRegistrar()
    handled = (signal.SIGTERM, signal.SIGINT)
    previous = tuple(signal.getsignal(process_signal) for process_signal in handled)

    # WHEN
    with registrar.register(lambda: None):
        installed = tuple(signal.getsignal(process_signal) for process_signal in handled)

    # THEN
    assert installed != previous
    assert tuple(signal.getsignal(process_signal) for process_signal in handled) == previous
