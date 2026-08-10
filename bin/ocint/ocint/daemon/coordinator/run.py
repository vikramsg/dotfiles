import asyncio
import errno
import fcntl
import os
import signal
import stat
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import AbstractContextManager, asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import FrameType, TracebackType
from typing import Protocol, Self

from ocint.daemon.coordinator.models import (
    DeliveryLookup,
    DeliveryMissing,
    DeliveryReceipt,
    DeliveryRequest,
    DeliveryState,
    OpenCodeAssistantMessageId,
    OpenCodeCompletion,
    OpenCodePromptObservation,
    OpenCodePromptRequest,
    OpenCodeSessionId,
    OpenCodeSessionRequest,
    OpenCodeUserMessageId,
    PromptPresence,
    Turn,
    TurnState,
)
from ocint.daemon.coordinator.repository import CoordinatorRepository
from ocint.daemon.coordinator.service import CoordinatorService
from ocint.daemon.logging import get_logger
from ocint.daemon.models import PromptObservation
from ocint.daemon.opencode import (
    OpenCodePrompt,
    OpenCodeResponse,
    RetryableOpenCodeError,
    TerminalOpenCodeError,
)


class OpenCodeCoordinator(Protocol):
    async def create_or_reuse_session(self, request: OpenCodeSessionRequest) -> OpenCodeSessionId: ...
    async def observe_prompt(self, request: OpenCodePromptRequest) -> OpenCodePromptObservation: ...
    async def submit_prompt(self, request: OpenCodePromptRequest) -> None: ...
    async def wait_for_completion(self, request: OpenCodePromptRequest) -> OpenCodeCompletion: ...


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


class CoordinatorDelivery(Protocol):
    async def find_delivery(self, request: DeliveryRequest) -> DeliveryLookup: ...
    async def post(self, request: DeliveryRequest) -> DeliveryReceipt: ...


class CoordinatorProcess(Protocol):
    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def wait_exited(self) -> int: ...


class CoordinatorIngress(Protocol):
    async def __call__(self, shutdown: asyncio.Event, /) -> None: ...


class ShutdownSignalRegistrar(Protocol):
    def register(self, request_shutdown: Callable[[], None]) -> AbstractContextManager[None]: ...


class ProcessSignalRegistrar:
    @contextmanager
    def register(self, request_shutdown: Callable[[], None]) -> Iterator[None]:
        def handle_shutdown(_signal_number: int, _frame: FrameType | None) -> None:
            request_shutdown()

        previous_termination_handler = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, handle_shutdown)
        try:
            previous_interrupt_handler = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, handle_shutdown)
            try:
                yield
            finally:
                signal.signal(signal.SIGINT, previous_interrupt_handler)
        finally:
            signal.signal(signal.SIGTERM, previous_termination_handler)


class CoordinatorStartupShutdown(Exception):
    """A requested shutdown that interrupted coordinator startup."""


class CoordinatorShutdown:
    def __init__(self) -> None:
        self.event = asyncio.Event()

    @property
    def requested(self) -> bool:
        return self.event.is_set()

    def request(self) -> None:
        self.event.set()

    async def wait(self) -> None:
        await self.event.wait()


class RetryableCoordinatorError(Exception):
    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        if retry_after_seconds is not None and retry_after_seconds <= 0:
            raise ValueError("retry delay must be positive")
        self.retry_after_seconds = retry_after_seconds


class RetryableCoordinatorDeliveryError(RetryableCoordinatorError):
    """A temporary delivery failure whose response remains valid."""


class TerminalCoordinatorError(Exception):
    """A classified adapter failure that should not be retried."""


class TerminalCoordinatorDeliveryError(Exception):
    """A delivery failure that must stop the worker without changing its response."""


class RuntimeFileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.descriptor = -1

    def __enter__(self) -> Self:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        information = os.fstat(descriptor)
        if not stat.S_ISREG(information.st_mode) or information.st_uid != os.getuid():
            os.close(descriptor)
            raise PermissionError(f"invalid coordinator runtime lock: {self.path}")
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(descriptor)
            if error.errno in (errno.EACCES, errno.EAGAIN):
                raise RuntimeError("another coordinator runtime owns the lock") from error
            raise
        self.descriptor = descriptor
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.descriptor >= 0:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
            os.close(self.descriptor)
            self.descriptor = -1


class CoordinatorRuntime:
    def __init__(
        self,
        repository: CoordinatorRepository,
        service: CoordinatorService,
        opencode: OpenCodeCoordinator,
        delivery: CoordinatorDelivery,
        workspace: Path,
        retry_seconds: float,
        max_turn_retries: int,
        orphan_retention_seconds: float,
        delivery_interval_seconds: float,
    ) -> None:
        if retry_seconds <= 0 or orphan_retention_seconds <= 0 or delivery_interval_seconds <= 0:
            raise ValueError("coordinator runtime intervals must be positive")
        if max_turn_retries <= 0:
            raise ValueError("maximum turn retries must be positive")
        self.repository = repository
        self.service = service
        self.opencode = opencode
        self.delivery = delivery
        self.workspace = workspace
        self.retry_seconds = retry_seconds
        self.max_turn_retries = max_turn_retries
        self.orphan_retention_seconds = orphan_retention_seconds
        self.delivery_interval_seconds = delivery_interval_seconds
        self.wakeup = asyncio.Event()
        self.logger = get_logger("coordinator.runtime")

    def wake(self) -> None:
        self.wakeup.set()

    async def run_once(self) -> bool:
        self.repository.expire_orphans(self._orphan_cutoff())
        turn = self.repository.claim_turn(self._now())
        if turn is None:
            return False
        self.logger.info(
            "Coordinator turn claimed",
            conversation=turn.conversation_id,
            turn=turn.id,
            state=turn.state.value,
            retry_count=turn.retry_count,
        )
        try:
            await self._process(turn)
        except RetryableCoordinatorDeliveryError as error:
            retried = self.repository.schedule_retry(
                turn.id,
                self._retry_at(error.retry_after_seconds or self.retry_seconds),
                turn.error,
            )
            self.logger.warning(
                "Coordinator delivery retry scheduled",
                conversation=turn.conversation_id,
                turn=turn.id,
                state=retried.state.value,
                retry_count=retried.retry_count,
                error_type=type(error).__name__,
            )
        except RetryableCoordinatorError as error:
            if turn.retry_count < self.max_turn_retries:
                retried = self.repository.schedule_retry(
                    turn.id,
                    self._retry_at(error.retry_after_seconds or self.retry_seconds),
                    str(error),
                )
                self.logger.warning(
                    "Coordinator turn retry scheduled",
                    conversation=turn.conversation_id,
                    turn=turn.id,
                    state=retried.state.value,
                    retry_count=retried.retry_count,
                    error_type=type(error).__name__,
                )
            else:
                self.logger.error(
                    "Coordinator turn retry budget exhausted",
                    conversation=turn.conversation_id,
                    turn=turn.id,
                    state=turn.state.value,
                    retry_count=turn.retry_count,
                    error_type=type(error).__name__,
                )
                await self._store_failure_and_deliver(turn, error)
        except TerminalCoordinatorError as error:
            self.logger.error(
                "Coordinator terminal OpenCode failure",
                conversation=turn.conversation_id,
                turn=turn.id,
                state=turn.state.value,
                retry_count=turn.retry_count,
                error_type=type(error).__name__,
            )
            await self._store_failure_and_deliver(turn, error)
        except TerminalCoordinatorDeliveryError:
            raise
        except Exception as error:
            self.logger.error(
                "Coordinator turn failed",
                conversation=turn.conversation_id,
                turn=turn.id,
                state=turn.state.value,
                retry_count=turn.retry_count,
                error_type=type(error).__name__,
            )
            await self._store_failure_and_deliver(turn, error)
        final = self.repository.turn(turn.id)
        self.logger.info(
            "Coordinator turn checkpoint",
            conversation=final.conversation_id,
            turn=final.id,
            state=final.state.value,
            retry_count=final.retry_count,
        )
        return True

    async def _store_failure_and_deliver(self, turn: Turn, error: Exception) -> None:
        failed = self.repository.store_failure_response(turn.id, str(error), self.service.safe_failure_text)
        try:
            await self._deliver(failed)
        except RetryableCoordinatorDeliveryError as delivery_error:
            self.repository.schedule_retry(
                turn.id,
                self._retry_at(delivery_error.retry_after_seconds or self.retry_seconds),
                failed.error,
            )

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            self.wakeup.clear()
            worked = await self.run_once()
            if worked:
                continue
            wake_task = asyncio.create_task(self.wakeup.wait())
            stop_task = asyncio.create_task(stop.wait())
            done, pending = await asyncio.wait(
                (wake_task, stop_task),
                timeout=self.retry_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.result()

    async def _process(self, turn: Turn) -> None:
        current = turn
        if current.state is TurnState.SESSION_READY:
            conversation = self.repository.conversation(current.conversation_id)
            if not conversation.opencode_session_id:
                self.logger.info(
                    "Coordinator OpenCode session requested",
                    conversation=current.conversation_id,
                    turn=current.id,
                )
                session_id = await self.opencode.create_or_reuse_session(
                    OpenCodeSessionRequest(
                        workspace=str(self.workspace),
                        identity=self.service.session_identity(conversation.identity),
                    )
                )
                conversation = self.repository.set_session(conversation.id, session_id.value)
                self.logger.info(
                    "Coordinator OpenCode session ready",
                    conversation=current.conversation_id,
                    turn=current.id,
                    session=session_id.value,
                )
            current = self.repository.mark_prompt_intended(current.id)

        if current.state in (TurnState.PROMPT_INTENDED, TurnState.PROMPT_SUBMITTED):
            conversation = self.repository.conversation(current.conversation_id)
            request = OpenCodePromptRequest(
                session_id=OpenCodeSessionId(conversation.opencode_session_id),
                user_message_id=OpenCodeUserMessageId(current.opencode_user_message_id),
                prompt=current.managed_prompt,
            )
            self.logger.info(
                "Coordinator OpenCode observation started",
                conversation=current.conversation_id,
                turn=current.id,
                session=request.session_id.value,
                message=request.user_message_id.value,
            )
            observation = await self.opencode.observe_prompt(request)
            if observation.presence is PromptPresence.COMPLETE:
                if observation.assistant_message_id is None:
                    raise RuntimeError("completed OpenCode prompt has no assistant message ID")
                current = self.repository.store_response(
                    current.id,
                    observation.assistant_message_id.value,
                    observation.text,
                )
                self.logger.info(
                    "Coordinator OpenCode completion recovered",
                    conversation=current.conversation_id,
                    turn=current.id,
                    session=request.session_id.value,
                    message=request.user_message_id.value,
                    assistant_message=observation.assistant_message_id.value,
                )
            else:
                if observation.presence is PromptPresence.INTERRUPTED:
                    raise RetryableCoordinatorError("OpenCode managed prompt is present but has no terminal response")
                if observation.presence is PromptPresence.ABSENT:
                    self.logger.info(
                        "Coordinator OpenCode submission started",
                        conversation=current.conversation_id,
                        turn=current.id,
                        session=request.session_id.value,
                        message=request.user_message_id.value,
                    )
                    await self.opencode.submit_prompt(request)
                current = self.repository.mark_prompt_submitted(current.id)
                completion = await self.opencode.wait_for_completion(request)
                current = self.repository.store_response(
                    current.id,
                    completion.assistant_message_id.value,
                    completion.text,
                )
                self.logger.info(
                    "Coordinator OpenCode completion stored",
                    conversation=current.conversation_id,
                    turn=current.id,
                    session=request.session_id.value,
                    message=request.user_message_id.value,
                    assistant_message=completion.assistant_message_id.value,
                )

        if current.state in (TurnState.RESPONSE_READY, TurnState.DELIVERING):
            await self._deliver(current)

    async def _deliver(self, turn: Turn) -> None:
        current = turn
        if current.state is TurnState.RESPONSE_READY:
            self.repository.create_deliveries(current.id, self.service.chunks(current.response_text))
            current = self.repository.turn(current.id)
        while True:
            chunk = self.repository.next_delivery(current.id, self._now())
            if chunk is None:
                deliveries = self.repository.deliveries(current.id)
                if deliveries and all(item.state is DeliveryState.DELIVERED for item in deliveries):
                    self.repository.complete_turn(current.id)
                return
            conversation = self.repository.conversation(current.conversation_id)
            request = DeliveryRequest(
                identity=conversation.identity,
                client_message_id=chunk.client_msg_id,
                text=chunk.text,
            )
            posted = False
            self.logger.info(
                "Coordinator Slack delivery checkpoint",
                turn=current.id,
                chunk_index=chunk.chunk_index,
                client_message=chunk.client_msg_id,
                state=chunk.state.value,
                retry_count=chunk.retry_count,
            )
            try:
                if chunk.state is DeliveryState.INTENDED:
                    receipt = await self.delivery.find_delivery(request)
                    if isinstance(receipt, DeliveryMissing):
                        receipt = await self.delivery.post(request)
                        posted = True
                    else:
                        self.logger.info(
                            "Coordinator Slack delivery recovered",
                            turn=current.id,
                            chunk_index=chunk.chunk_index,
                            client_message=chunk.client_msg_id,
                            provider_message=receipt.provider_message_id,
                        )
                else:
                    self.repository.mark_delivery_intended(chunk.turn_id, chunk.chunk_index)
                    receipt = await self.delivery.post(request)
                    posted = True
            except RetryableCoordinatorError as error:
                retry_after_seconds = error.retry_after_seconds or self.retry_seconds
                retried = self.repository.schedule_delivery_retry(
                    chunk.turn_id,
                    chunk.chunk_index,
                    self._retry_at(retry_after_seconds),
                )
                self.logger.warning(
                    "Coordinator Slack delivery retry scheduled",
                    turn=current.id,
                    chunk_index=chunk.chunk_index,
                    client_message=chunk.client_msg_id,
                    state=retried.state.value,
                    retry_count=retried.retry_count,
                    error_type=type(error).__name__,
                )
                raise RetryableCoordinatorDeliveryError(str(error), retry_after_seconds) from error
            except Exception as error:
                raise TerminalCoordinatorDeliveryError("coordinator delivery failed") from error
            self.repository.mark_delivered(chunk.turn_id, chunk.chunk_index, receipt.provider_message_id)
            self.logger.info(
                "Coordinator Slack delivery stored",
                turn=current.id,
                chunk_index=chunk.chunk_index,
                client_message=chunk.client_msg_id,
                provider_message=receipt.provider_message_id,
            )
            if posted and self.repository.next_delivery(current.id, self._now()) is not None:
                await asyncio.sleep(self.delivery_interval_seconds)

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _retry_at(seconds: float) -> str:
        return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()

    def _orphan_cutoff(self) -> str:
        return (datetime.now(UTC) - timedelta(seconds=self.orphan_retention_seconds)).isoformat()


@dataclass(frozen=True)
class CoordinatorApplicationRequest:
    runtime: CoordinatorRuntime
    opencode: CoordinatorProcess
    ingress: CoordinatorIngress
    ingress_host: str
    ingress_port: int
    runtime_lock: Path
    shutdown_timeout_seconds: float
    signal_registrar: ShutdownSignalRegistrar = field(default_factory=ProcessSignalRegistrar)


class CoordinatorApplication:
    def __init__(
        self,
        request: CoordinatorApplicationRequest,
        worker_stop: asyncio.Event,
        ingress_shutdown: asyncio.Event,
        worker: asyncio.Task[None],
        ingress: asyncio.Task[None],
        child: asyncio.Task[int],
        shutdown: CoordinatorShutdown,
    ) -> None:
        self.request = request
        self.worker_stop = worker_stop
        self.ingress_shutdown = ingress_shutdown
        self.worker = worker
        self.ingress = ingress
        self.child = child
        self.shutdown = shutdown
        self.logger = get_logger("coordinator.lifecycle")
        self.closed = False

    def request_shutdown(self) -> None:
        self.shutdown.request()

    async def wait(self) -> None:
        shutdown = asyncio.create_task(self.shutdown.wait())
        try:
            await asyncio.wait(
                (self.worker, self.ingress, self.child, shutdown),
                return_when=asyncio.FIRST_COMPLETED,
            )
            self._raise_if_supervision_stopped()
            if shutdown.done():
                shutdown.result()
                return
            raise RuntimeError("coordinator application wait ended without a completed operation")
        finally:
            shutdown.cancel()
            await asyncio.gather(shutdown, return_exceptions=True)

    def raise_if_stopped(self) -> None:
        self._raise_if_supervision_stopped()

    def _raise_if_supervision_stopped(self) -> None:
        if self.child.done():
            status = self.child.result()
            self.logger.error("Coordinator OpenCode child exited", exit_status=status)
            raise RuntimeError(f"OpenCode exited unexpectedly ({status})")
        completed = tuple(task for task in (self.worker, self.ingress) if task.done())
        if not completed:
            return
        errors: list[BaseException] = []
        for task in completed:
            if task.cancelled():
                errors.append(RuntimeError("coordinator supervised operation was cancelled unexpectedly"))
                continue
            error = task.exception()
            if error is not None:
                errors.append(error)
        if errors:
            raise errors[0]
        raise RuntimeError("coordinator application stopped unexpectedly")

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.logger.info("Coordinator bounded shutdown started")
        self.worker_stop.set()
        self.ingress_shutdown.set()
        tasks = (self.worker, self.ingress)
        outcome = "completed"
        try:
            async with asyncio.timeout(self.request.shutdown_timeout_seconds):
                await asyncio.gather(*tasks, return_exceptions=True)
        except TimeoutError:
            outcome = "cancelled"
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        self.child.cancel()
        await asyncio.gather(self.child, return_exceptions=True)
        self.logger.info("Coordinator bounded shutdown completed", shutdown_outcome=outcome)


async def run_coordinator_application(request: CoordinatorApplicationRequest) -> None:
    try:
        async with open_coordinator_application(request) as application:
            await application.wait()
    except CoordinatorStartupShutdown:
        get_logger("coordinator.lifecycle").info("Coordinator stopped during OpenCode startup")


@asynccontextmanager
async def open_coordinator_application(
    request: CoordinatorApplicationRequest,
) -> AsyncIterator[CoordinatorApplication]:
    if request.shutdown_timeout_seconds <= 0:
        raise ValueError("shutdown timeout must be positive")
    logger = get_logger("coordinator.lifecycle")
    with RuntimeFileLock(request.runtime_lock):
        logger.info(
            "Coordinator runtime lock acquired",
            pid=os.getpid(),
            host=request.ingress_host,
            port=request.ingress_port,
        )
        shutdown = CoordinatorShutdown()
        with request.signal_registrar.register(shutdown.request):
            logger.info("Coordinator OpenCode startup started")
            try:
                await _start_opencode_or_shutdown(request.opencode, shutdown)
            except CoordinatorStartupShutdown:
                logger.info("Coordinator OpenCode startup stopped by requested shutdown")
                await request.opencode.close()
                raise
            except BaseException:
                logger.error("Coordinator OpenCode startup failed")
                await request.opencode.close()
                raise
            logger.info("Coordinator OpenCode startup completed")
            worker_stop = asyncio.Event()
            ingress_shutdown = asyncio.Event()
            worker = asyncio.create_task(request.runtime.run(worker_stop))
            ingress = asyncio.create_task(request.ingress(ingress_shutdown))
            child = asyncio.create_task(request.opencode.wait_exited())
            logger.info("Coordinator ingress and worker started", host=request.ingress_host, port=request.ingress_port)
            application = CoordinatorApplication(
                request,
                worker_stop,
                ingress_shutdown,
                worker,
                ingress,
                child,
                shutdown,
            )
            try:
                yield application
            finally:
                await application.close()
                logger.info("Coordinator OpenCode shutdown started")
                await request.opencode.close()
                logger.info("Coordinator OpenCode shutdown completed")


async def _start_opencode_or_shutdown(opencode: CoordinatorProcess, shutdown: CoordinatorShutdown) -> None:
    if shutdown.requested:
        raise CoordinatorStartupShutdown
    startup = asyncio.create_task(opencode.start())
    requested = asyncio.create_task(shutdown.wait())
    try:
        await asyncio.wait((startup, requested), return_when=asyncio.FIRST_COMPLETED)
        if startup.done():
            startup.result()
        if requested.done():
            if not startup.done():
                startup.cancel()
                await asyncio.gather(startup, return_exceptions=True)
            raise CoordinatorStartupShutdown
        await startup
    finally:
        if not startup.done():
            startup.cancel()
            await asyncio.gather(startup, return_exceptions=True)
        requested.cancel()
        await asyncio.gather(requested, return_exceptions=True)
