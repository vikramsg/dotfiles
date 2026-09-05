import asyncio
from pathlib import Path

import pytest
from ocint.daemon.coordinator import (
    ActorKind,
    ChannelAccess,
    ConversationIdentity,
    ConversationMessage,
    DeliveryMissing,
    DeliveryReceipt,
    DeliveryRequest,
    MessageKind,
    RetryableCoordinatorError,
    TerminalCoordinatorDeliveryError,
    TerminalCoordinatorError,
)
from ocint.daemon.coordinator.models import (
    DeliveryLookup,
    OpenCodeAssistantMessageId,
    OpenCodeCompletion,
    OpenCodePromptObservation,
    OpenCodePromptRequest,
    OpenCodeSessionId,
    OpenCodeSessionRequest,
    PromptPresence,
    TurnState,
)
from ocint.daemon.coordinator.repository import CoordinatorRepository
from ocint.daemon.coordinator.run import CoordinatorRuntime
from ocint.daemon.coordinator.service import ConfiguredAuthorizationPolicy, CoordinatorService
from ocint.daemon.db import create_daemon_engine
from ocint.daemon.db.schema import metadata


class FakeOpenCode:
    def __init__(
        self,
        response: str,
        *,
        retry_observation_once: bool = False,
        retry_submitted_observations: int = 0,
        interrupted_submitted_observations: int = 0,
        retry_completion_once: bool = False,
        terminal_failure: bool = False,
    ) -> None:
        self.response = response
        self.sessions: list[OpenCodeSessionRequest] = []
        self.submissions: list[OpenCodePromptRequest] = []
        self.observations = 0
        self.completion_waits = 0
        self.retry_observation_once = retry_observation_once
        self.retry_submitted_observations = retry_submitted_observations
        self.interrupted_submitted_observations = interrupted_submitted_observations
        self.retry_completion_once = retry_completion_once
        self.terminal_failure = terminal_failure

    async def create_or_reuse_session(self, request: OpenCodeSessionRequest) -> OpenCodeSessionId:
        self.sessions.append(request)
        return OpenCodeSessionId("session-1")

    async def observe_prompt(self, request: OpenCodePromptRequest) -> OpenCodePromptObservation:
        self.observations += 1
        if self.retry_observation_once and self.observations == 1:
            raise RetryableCoordinatorError("temporary OpenCode failure")
        if self.terminal_failure:
            raise TerminalCoordinatorError("terminal provider failure")
        if request in self.submissions:
            if self.retry_submitted_observations > 0:
                self.retry_submitted_observations -= 1
                raise RetryableCoordinatorError("persisted retryable OpenCode error")
            if self.interrupted_submitted_observations > 0:
                self.interrupted_submitted_observations -= 1
                return OpenCodePromptObservation(presence=PromptPresence.INTERRUPTED)
            return OpenCodePromptObservation(
                presence=PromptPresence.COMPLETE,
                assistant_message_id=OpenCodeAssistantMessageId(f"assistant-{len(self.submissions)}"),
                text=self.response,
            )
        return OpenCodePromptObservation(presence=PromptPresence.ABSENT)

    async def submit_prompt(self, request: OpenCodePromptRequest) -> None:
        self.submissions.append(request)

    async def wait_for_completion(self, request: OpenCodePromptRequest) -> OpenCodeCompletion:
        _ = request
        self.completion_waits += 1
        if self.retry_completion_once and self.completion_waits == 1:
            raise RetryableCoordinatorError("completion result was not observed")
        return OpenCodeCompletion(
            assistant_message_id=OpenCodeAssistantMessageId(f"assistant-{len(self.submissions)}"),
            text=self.response,
        )


class FakeDelivery:
    def __init__(
        self,
        *,
        retry_once: bool = False,
        retry_attempt: int = 0,
        retry_attempts: int = 0,
        accept_before_retry: bool = False,
        terminal_failure: bool = False,
    ) -> None:
        self.posts: list[DeliveryRequest] = []
        self.attempts: list[DeliveryRequest] = []
        self.retry_attempt = 1 if retry_once else retry_attempt
        self.retry_attempts = retry_attempts
        self.accept_before_retry = accept_before_retry
        self.terminal_failure = terminal_failure

    async def find_delivery(self, request: DeliveryRequest) -> DeliveryLookup:
        for index, posted in enumerate(self.posts, start=1):
            if posted.client_message_id == request.client_message_id:
                return DeliveryReceipt(provider_message_id=f"provider-{index}")
        return DeliveryMissing()

    async def post(self, request: DeliveryRequest) -> DeliveryReceipt:
        self.attempts.append(request)
        if len(self.attempts) <= self.retry_attempts or (
            self.retry_attempt and len(self.attempts) == self.retry_attempt
        ):
            if self.accept_before_retry:
                self.posts.append(request)
            raise RetryableCoordinatorError("temporary chat delivery failure", 0.001)
        if self.terminal_failure:
            raise RuntimeError("terminal chat delivery failure")
        self.posts.append(request)
        return DeliveryReceipt(provider_message_id=f"provider-{len(self.posts)}")


@pytest.mark.asyncio
async def test_fake_adapters_process_a_thread_once_reuse_session_and_deliver_a_long_exact_response(
    tmp_path: Path,
) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "coordinator.sqlite")
    metadata.create_all(engine)
    repository = CoordinatorRepository(engine)
    policy = ConfiguredAuthorizationPolicy(
        (ChannelAccess(provider="chat", workspace="w", channel="c", authorized_actors=frozenset(("alice",))),)
    )
    service = CoordinatorService(policy, 100, "safe failure")
    response = "🙂" * 8_100
    opencode = FakeOpenCode(response)
    delivery = FakeDelivery()
    runtime = CoordinatorRuntime(repository, service, opencode, delivery, tmp_path, 1, 3, 3_600, 0.001)
    identity = ConversationIdentity(provider="chat", workspace="w", channel="c", thread="1.000001")
    for event_id, timestamp, kind in (
        ("root-event", "1.000001", MessageKind.ROOT),
        ("reply-event", "1.000002", MessageKind.REPLY),
    ):
        message = ConversationMessage(
            provider_event_id=event_id,
            conversation_identity=identity,
            message_id=timestamp,
            actor_id="alice",
            text=event_id,
            source_created_at=timestamp,
            source_order_at=1_000_000 + int(timestamp[-1]),
        )
        repository.ingest(service.prepare(message, kind, ActorKind.HUMAN))
    duplicate = ConversationMessage(
        provider_event_id="reply-event",
        conversation_identity=identity,
        message_id="1.000002",
        actor_id="alice",
        text="reply-event",
        source_created_at="1.000002",
        source_order_at=1_000_002,
    )
    repository.ingest(service.prepare(duplicate, MessageKind.REPLY, ActorKind.HUMAN))

    # WHEN
    assert await runtime.run_once()
    assert await runtime.run_once()
    assert not await runtime.run_once()

    # THEN
    turns = repository.turns(1)
    assert [turn.state for turn in turns] == [TurnState.COMPLETED, TurnState.COMPLETED]
    assert len(opencode.sessions) == 1
    assert len(opencode.submissions) == 2
    assert len({request.user_message_id.value for request in opencode.submissions}) == 2
    assert all(request.user_message_id.value.startswith("msg_") for request in opencode.submissions)
    first_turn_posts = delivery.posts[: len(repository.deliveries(turns[0].id))]
    assert service.reconstruct(service.chunks(response)) == response
    assert all(len(post.text) <= 100 for post in first_turn_posts)
    assert len(delivery.posts) > 2
    engine.dispose()


@pytest.mark.asyncio
async def test_restart_after_prompt_submission_observes_the_same_logical_prompt_without_resubmitting(
    tmp_path: Path,
) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "coordinator.sqlite")
    metadata.create_all(engine)
    repository = CoordinatorRepository(engine)
    service = CoordinatorService(
        ConfiguredAuthorizationPolicy(
            (ChannelAccess(provider="chat", workspace="w", channel="c", authorized_actors=frozenset(("alice",))),)
        ),
        100,
        "safe failure",
    )
    opencode = FakeOpenCode("durable answer", retry_completion_once=True)
    delivery = FakeDelivery()
    runtime = CoordinatorRuntime(repository, service, opencode, delivery, tmp_path, 0.001, 3, 3_600, 0.001)
    result = repository.ingest(
        service.prepare(
            ConversationMessage(
                provider_event_id="restart-event",
                conversation_identity=ConversationIdentity(
                    provider="chat", workspace="w", channel="c", thread="1.000001"
                ),
                message_id="1.000001",
                actor_id="alice",
                text="work once",
                source_created_at="1.000001",
                source_order_at=1_000_001,
            ),
            MessageKind.ROOT,
            ActorKind.HUMAN,
        )
    )

    # WHEN
    assert await runtime.run_once()
    submitted = repository.turn(result.turn_ids[0])
    await asyncio.sleep(0.01)
    restarted = CoordinatorRuntime(repository, service, opencode, delivery, tmp_path, 0.001, 3, 3_600, 0.001)
    assert await restarted.run_once()

    # THEN
    assert submitted.state is TurnState.PROMPT_SUBMITTED
    assert len(opencode.submissions) == 1
    assert repository.turn(result.turn_ids[0]).state is TurnState.COMPLETED
    assert delivery.posts[0].text.endswith("durable answer")
    engine.dispose()


@pytest.mark.asyncio
async def test_restart_terminal_prompt_observation_delivers_safe_failure_without_resubmitting(
    tmp_path: Path,
) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "coordinator.sqlite")
    metadata.create_all(engine)
    repository = CoordinatorRepository(engine)
    service = CoordinatorService(
        ConfiguredAuthorizationPolicy(
            (ChannelAccess(provider="chat", workspace="w", channel="c", authorized_actors=frozenset(("alice",))),)
        ),
        100,
        "safe failure",
    )
    opencode = FakeOpenCode("unused", retry_completion_once=True)
    delivery = FakeDelivery()
    runtime = CoordinatorRuntime(repository, service, opencode, delivery, tmp_path, 0.001, 3, 3_600, 0.001)
    result = repository.ingest(
        service.prepare(
            ConversationMessage(
                provider_event_id="terminal-restart-event",
                conversation_identity=ConversationIdentity(
                    provider="chat", workspace="w", channel="c", thread="1.000001"
                ),
                message_id="1.000001",
                actor_id="alice",
                text="work once",
                source_created_at="1.000001",
                source_order_at=1_000_001,
            ),
            MessageKind.ROOT,
            ActorKind.HUMAN,
        )
    )
    assert await runtime.run_once()
    assert repository.turn(result.turn_ids[0]).state is TurnState.PROMPT_SUBMITTED
    opencode.terminal_failure = True
    await asyncio.sleep(0.01)

    # WHEN
    restarted = CoordinatorRuntime(repository, service, opencode, delivery, tmp_path, 0.001, 3, 3_600, 0.001)
    assert await restarted.run_once()

    # THEN
    stored = repository.turn(result.turn_ids[0])
    assert stored.state is TurnState.FAILED
    assert stored.response_text == service.safe_failure_text
    assert len(opencode.submissions) == 1
    assert [post.text for post in delivery.posts] == ["[1/1] safe failure"]
    engine.dispose()


@pytest.mark.asyncio
async def test_restart_retryable_prompt_observation_schedules_retry_without_resubmitting(
    tmp_path: Path,
) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "coordinator.sqlite")
    metadata.create_all(engine)
    repository = CoordinatorRepository(engine)
    service = CoordinatorService(
        ConfiguredAuthorizationPolicy(
            (ChannelAccess(provider="chat", workspace="w", channel="c", authorized_actors=frozenset(("alice",))),)
        ),
        100,
        "safe failure",
    )
    opencode = FakeOpenCode("durable answer", retry_completion_once=True)
    delivery = FakeDelivery()
    runtime = CoordinatorRuntime(repository, service, opencode, delivery, tmp_path, 0.001, 3, 3_600, 0.001)
    result = repository.ingest(
        service.prepare(
            ConversationMessage(
                provider_event_id="retryable-restart-event",
                conversation_identity=ConversationIdentity(
                    provider="chat", workspace="w", channel="c", thread="1.000001"
                ),
                message_id="1.000001",
                actor_id="alice",
                text="work once",
                source_created_at="1.000001",
                source_order_at=1_000_001,
            ),
            MessageKind.ROOT,
            ActorKind.HUMAN,
        )
    )
    assert await runtime.run_once()
    opencode.retry_observation_once = True
    opencode.observations = 0
    await asyncio.sleep(0.01)

    # WHEN
    restarted = CoordinatorRuntime(repository, service, opencode, delivery, tmp_path, 0.001, 3, 3_600, 0.001)
    assert await restarted.run_once()

    # THEN
    retried = repository.turn(result.turn_ids[0])
    assert retried.state is TurnState.PROMPT_SUBMITTED
    assert retried.retry_count == 2
    assert retried.response_text == ""
    assert len(opencode.submissions) == 1
    assert delivery.posts == []
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("retryable_observations", "interrupted_observations"),
    [(3, 0), (0, 3)],
    ids=("persisted-retryable-error", "interrupted-prompt"),
)
async def test_repeated_opencode_recovery_exhausts_the_budget_and_unblocks_the_next_ordered_turn(
    tmp_path: Path,
    retryable_observations: int,
    interrupted_observations: int,
) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "coordinator.sqlite")
    metadata.create_all(engine)
    repository = CoordinatorRepository(engine)
    service = CoordinatorService(
        ConfiguredAuthorizationPolicy(
            (ChannelAccess(provider="chat", workspace="w", channel="c", authorized_actors=frozenset(("alice",))),)
        ),
        100,
        "safe failure",
    )
    opencode = FakeOpenCode(
        "answer after failed turn",
        retry_submitted_observations=retryable_observations,
        interrupted_submitted_observations=interrupted_observations,
        retry_completion_once=True,
    )
    delivery = FakeDelivery()
    runtime = CoordinatorRuntime(repository, service, opencode, delivery, tmp_path, 0.001, 3, 3_600, 0.001)
    identity = ConversationIdentity(provider="chat", workspace="w", channel="c", thread="1.000001")
    for event_id, timestamp, kind in (
        ("failed-root", "1.000001", MessageKind.ROOT),
        ("ordered-reply", "1.000002", MessageKind.REPLY),
    ):
        repository.ingest(
            service.prepare(
                ConversationMessage(
                    provider_event_id=event_id,
                    conversation_identity=identity,
                    message_id=timestamp,
                    actor_id="alice",
                    text=event_id,
                    source_created_at=timestamp,
                    source_order_at=1_000_000 + int(timestamp[-1]),
                ),
                kind,
                ActorKind.HUMAN,
            )
        )

    # WHEN
    assert await runtime.run_once()
    for _attempt in range(3):
        await asyncio.sleep(0.01)
        assert await runtime.run_once()
    failed, waiting = repository.turns(1)
    assert len(opencode.submissions) == 1
    assert await runtime.run_once()

    # THEN
    completed = repository.turn(waiting.id)
    assert failed.state is TurnState.FAILED
    assert failed.retry_count == 3
    assert failed.response_text == service.safe_failure_text
    assert completed.state is TurnState.COMPLETED
    assert len(opencode.submissions) == 2
    assert len({request.user_message_id.value for request in opencode.submissions}) == 2
    assert [post.text for post in delivery.posts] == [
        "[1/1] safe failure",
        "[1/1] answer after failed turn",
    ]
    engine.dispose()


@pytest.mark.asyncio
async def test_uncertain_chat_acceptance_is_recovered_by_client_message_id_without_a_duplicate(
    tmp_path: Path,
) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "coordinator.sqlite")
    metadata.create_all(engine)
    repository = CoordinatorRepository(engine)
    service = CoordinatorService(
        ConfiguredAuthorizationPolicy(
            (ChannelAccess(provider="chat", workspace="w", channel="c", authorized_actors=frozenset(("alice",))),)
        ),
        100,
        "safe failure",
    )
    delivery = FakeDelivery(retry_attempt=1, accept_before_retry=True)
    runtime = CoordinatorRuntime(
        repository, service, FakeOpenCode("accepted answer"), delivery, tmp_path, 0.001, 3, 3_600, 0.001
    )
    result = repository.ingest(
        service.prepare(
            ConversationMessage(
                provider_event_id="uncertain-event",
                conversation_identity=ConversationIdentity(
                    provider="chat", workspace="w", channel="c", thread="1.000001"
                ),
                message_id="1.000001",
                actor_id="alice",
                text="deliver once",
                source_created_at="1.000001",
                source_order_at=1_000_001,
            ),
            MessageKind.ROOT,
            ActorKind.HUMAN,
        )
    )

    # WHEN
    assert await runtime.run_once()
    await asyncio.sleep(0.01)
    restarted = CoordinatorRuntime(repository, service, runtime.opencode, delivery, tmp_path, 0.001, 3, 3_600, 0.001)
    assert await restarted.run_once()

    # THEN
    assert repository.turn(result.turn_ids[0]).state is TurnState.COMPLETED
    assert len(delivery.attempts) == 1
    assert len(delivery.posts) == 1
    assert repository.deliveries(result.turn_ids[0])[0].provider_message_id == "provider-1"
    engine.dispose()


@pytest.mark.asyncio
async def test_middle_chunk_rate_limit_resumes_the_same_chunk_and_preserves_order(tmp_path: Path) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "coordinator.sqlite")
    metadata.create_all(engine)
    repository = CoordinatorRepository(engine)
    service = CoordinatorService(
        ConfiguredAuthorizationPolicy(
            (ChannelAccess(provider="chat", workspace="w", channel="c", authorized_actors=frozenset(("alice",))),)
        ),
        20,
        "safe failure",
    )
    delivery = FakeDelivery(retry_attempt=2)
    runtime = CoordinatorRuntime(
        repository,
        service,
        FakeOpenCode("abcdefghijklmnopqrstuvwxyz0123456789"),
        delivery,
        tmp_path,
        0.001,
        3,
        3_600,
        0.001,
    )
    result = repository.ingest(
        service.prepare(
            ConversationMessage(
                provider_event_id="rate-limit-event",
                conversation_identity=ConversationIdentity(
                    provider="chat", workspace="w", channel="c", thread="1.000001"
                ),
                message_id="1.000001",
                actor_id="alice",
                text="deliver chunks",
                source_created_at="1.000001",
                source_order_at=1_000_001,
            ),
            MessageKind.ROOT,
            ActorKind.HUMAN,
        )
    )

    # WHEN
    assert await runtime.run_once()
    await asyncio.sleep(0.01)
    assert await runtime.run_once()

    # THEN
    deliveries = repository.deliveries(result.turn_ids[0])
    identifiers = [item.client_msg_id for item in deliveries]
    assert len(identifiers) >= 3
    assert [attempt.client_message_id for attempt in delivery.attempts] == [
        identifiers[0],
        identifiers[1],
        identifiers[1],
        *identifiers[2:],
    ]
    assert [post.client_message_id for post in delivery.posts] == identifiers
    assert [post.text for post in delivery.posts] == [item.text for item in deliveries]
    assert repository.turn(result.turn_ids[0]).state is TurnState.COMPLETED
    engine.dispose()


@pytest.mark.asyncio
async def test_bot_root_cannot_create_a_recursive_turn_through_the_runtime_boundary(tmp_path: Path) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "coordinator.sqlite")
    metadata.create_all(engine)
    repository = CoordinatorRepository(engine)
    service = CoordinatorService(
        ConfiguredAuthorizationPolicy(
            (ChannelAccess(provider="chat", workspace="w", channel="c", authorized_actors=frozenset(("alice",))),)
        ),
        100,
        "safe failure",
    )
    opencode = FakeOpenCode("must not run")
    delivery = FakeDelivery()
    runtime = CoordinatorRuntime(repository, service, opencode, delivery, tmp_path, 1, 3, 3_600, 0.001)

    # WHEN
    result = repository.ingest(
        service.prepare(
            ConversationMessage(
                provider_event_id="bot-event",
                conversation_identity=ConversationIdentity(
                    provider="chat", workspace="w", channel="c", thread="1.000001"
                ),
                message_id="1.000001",
                actor_id="coordinator-bot",
                text="coordinator answer",
                source_created_at="1.000001",
                source_order_at=1_000_001,
            ),
            MessageKind.ROOT,
            ActorKind.BOT,
        )
    )

    # THEN
    assert result.turn_ids == ()
    assert not await runtime.run_once()
    assert opencode.sessions == []
    assert opencode.submissions == []
    assert delivery.posts == []
    engine.dispose()


@pytest.mark.asyncio
async def test_terminal_delivery_error_preserves_valid_opencode_response_and_fails_worker(tmp_path: Path) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "coordinator.sqlite")
    metadata.create_all(engine)
    repository = CoordinatorRepository(engine)
    service = CoordinatorService(
        ConfiguredAuthorizationPolicy(
            (ChannelAccess(provider="chat", workspace="w", channel="c", authorized_actors=frozenset(("alice",))),)
        ),
        100,
        "safe failure",
    )
    delivery = FakeDelivery(terminal_failure=True)
    runtime = CoordinatorRuntime(
        repository, service, FakeOpenCode("valid answer"), delivery, tmp_path, 1, 3, 3_600, 0.001
    )
    message = ConversationMessage(
        provider_event_id="root-event",
        conversation_identity=ConversationIdentity(provider="chat", workspace="w", channel="c", thread="1.000001"),
        message_id="1.000001",
        actor_id="alice",
        text="work",
        source_created_at="1.000001",
        source_order_at=1_000_001,
    )
    result = repository.ingest(service.prepare(message, MessageKind.ROOT, ActorKind.HUMAN))

    # WHEN / THEN
    with pytest.raises(TerminalCoordinatorDeliveryError, match="delivery failed"):
        await runtime.run_once()
    stored = repository.turn(result.turn_ids[0])
    assert stored.state is TurnState.DELIVERING
    assert stored.response_text == "valid answer"
    assert stored.response_text != service.safe_failure_text
    engine.dispose()


@pytest.mark.asyncio
async def test_transient_delivery_retries_beyond_the_opencode_budget_and_preserves_the_response(
    tmp_path: Path,
) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "coordinator.sqlite")
    metadata.create_all(engine)
    repository = CoordinatorRepository(engine)
    service = CoordinatorService(
        ConfiguredAuthorizationPolicy(
            (ChannelAccess(provider="chat", workspace="w", channel="c", authorized_actors=frozenset(("alice",))),)
        ),
        100,
        "safe failure",
    )
    delivery = FakeDelivery(retry_attempts=3)
    runtime = CoordinatorRuntime(
        repository, service, FakeOpenCode("valid answer"), delivery, tmp_path, 0.001, 1, 3_600, 0.001
    )
    message = ConversationMessage(
        provider_event_id="root-event",
        conversation_identity=ConversationIdentity(provider="chat", workspace="w", channel="c", thread="1.000001"),
        message_id="1.000001",
        actor_id="alice",
        text="work",
        source_created_at="1.000001",
        source_order_at=1_000_001,
    )
    result = repository.ingest(service.prepare(message, MessageKind.ROOT, ActorKind.HUMAN))

    # WHEN
    assert await runtime.run_once()
    response_ready = repository.turn(result.turn_ids[0])
    for _attempt in range(3):
        await asyncio.sleep(0.01)
        assert await runtime.run_once()

    # THEN
    completed = repository.turn(result.turn_ids[0])
    assert response_ready.response_text == "valid answer"
    assert completed.state is TurnState.COMPLETED
    assert completed.retry_count == 3
    assert completed.response_text == "valid answer"
    assert len(delivery.attempts) == 4
    assert len({attempt.client_message_id for attempt in delivery.attempts}) == 1
    engine.dispose()


@pytest.mark.asyncio
async def test_transient_opencode_failure_before_response_retries_without_safe_failure(tmp_path: Path) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "coordinator.sqlite")
    metadata.create_all(engine)
    repository = CoordinatorRepository(engine)
    service = CoordinatorService(
        ConfiguredAuthorizationPolicy(
            (ChannelAccess(provider="chat", workspace="w", channel="c", authorized_actors=frozenset(("alice",))),)
        ),
        100,
        "safe failure",
    )
    opencode = FakeOpenCode("valid answer", retry_observation_once=True)
    delivery = FakeDelivery()
    runtime = CoordinatorRuntime(repository, service, opencode, delivery, tmp_path, 0.001, 3, 3_600, 0.001)
    message = ConversationMessage(
        provider_event_id="root-event",
        conversation_identity=ConversationIdentity(provider="chat", workspace="w", channel="c", thread="1.000001"),
        message_id="1.000001",
        actor_id="alice",
        text="work",
        source_created_at="1.000001",
        source_order_at=1_000_001,
    )
    result = repository.ingest(service.prepare(message, MessageKind.ROOT, ActorKind.HUMAN))

    # WHEN
    assert await runtime.run_once()
    after_transient = repository.turn(result.turn_ids[0])
    await asyncio.sleep(0.01)
    assert await runtime.run_once()

    # THEN
    assert after_transient.response_text == ""
    assert after_transient.retry_count == 1
    assert repository.turn(result.turn_ids[0]).state is TurnState.COMPLETED
    assert delivery.posts[0].text.endswith("valid answer")
    engine.dispose()


@pytest.mark.asyncio
async def test_terminal_provider_error_preserves_one_safe_failure_through_delivery_retries(tmp_path: Path) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "coordinator.sqlite")
    metadata.create_all(engine)
    repository = CoordinatorRepository(engine)
    service = CoordinatorService(
        ConfiguredAuthorizationPolicy(
            (ChannelAccess(provider="chat", workspace="w", channel="c", authorized_actors=frozenset(("alice",))),)
        ),
        100,
        "safe failure",
    )
    delivery = FakeDelivery(retry_attempts=2)
    runtime = CoordinatorRuntime(
        repository,
        service,
        FakeOpenCode("unused", terminal_failure=True),
        delivery,
        tmp_path,
        1,
        1,
        3_600,
        0.001,
    )
    message = ConversationMessage(
        provider_event_id="root-event",
        conversation_identity=ConversationIdentity(provider="chat", workspace="w", channel="c", thread="1.000001"),
        message_id="1.000001",
        actor_id="alice",
        text="work",
        source_created_at="1.000001",
        source_order_at=1_000_001,
    )
    result = repository.ingest(service.prepare(message, MessageKind.ROOT, ActorKind.HUMAN))

    # WHEN
    assert await runtime.run_once()
    persisted = repository.turn(result.turn_ids[0])
    for _attempt in range(2):
        await asyncio.sleep(0.01)
        assert await runtime.run_once()

    # THEN
    stored = repository.turn(result.turn_ids[0])
    assert persisted.response_text == service.safe_failure_text
    assert stored.state is TurnState.FAILED
    assert stored.retry_count == 2
    assert stored.response_text == service.safe_failure_text
    assert stored.error == "terminal provider failure"
    assert [post.text for post in delivery.posts] == ["[1/1] safe failure"]
    engine.dispose()
