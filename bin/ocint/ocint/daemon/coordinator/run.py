import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ocint.daemon.coordinator.contracts import (
    CoordinatorDelivery,
    CoordinatorOperations,
    CoordinatorPersistence,
    OpenCodeCoordinator,
    RetryableCoordinatorDeliveryError,
    RetryableCoordinatorError,
    TerminalCoordinatorDeliveryError,
    TerminalCoordinatorError,
)
from ocint.daemon.coordinator.models import (
    DeliveryMissing,
    DeliveryRequest,
    DeliveryState,
    OpenCodePromptRequest,
    OpenCodeSessionId,
    OpenCodeSessionRequest,
    OpenCodeUserMessageId,
    PromptPresence,
    Turn,
    TurnState,
)
from ocint.daemon.logging import get_logger


class CoordinatorRuntime:
    def __init__(
        self,
        repository: CoordinatorPersistence,
        service: CoordinatorOperations,
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
                "Coordinator delivery checkpoint",
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
                            "Coordinator delivery recovered",
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
                    "Coordinator delivery retry scheduled",
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
                "Coordinator delivery stored",
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
