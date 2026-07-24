from dataclasses import dataclass, field
from pathlib import Path

import pytest
from ocint.daemon.db import create_daemon_engine
from ocint.daemon.db.schema import metadata
from ocint.daemon.models import (
    GitHubLogin,
    ObservedMessage,
    ObservedMessages,
    ReplyRequest,
    ThreadObservation,
    ThreadObservations,
    ThreadOrigin,
)
from ocint.daemon.pull_request_job import PullRequestJob, PullRequestJobRequest, PullRequestJobState
from ocint.daemon.pull_request_job.repository import PullRequestJobRepository
from ocint.daemon.tasks.models import MessageClassification, TaskKind, TaskState
from ocint.daemon.tasks.repository import TaskRepository
from ocint.daemon.tasks.run import TaskCoordinator


@dataclass
class FakeSource:
    eligible_state: bool
    observations: ThreadObservations = field(default_factory=lambda: ThreadObservations(root=[]))

    async def observe(self) -> ThreadObservations:
        return self.observations

    async def reply(self, request: ReplyRequest) -> ObservedMessage:
        raise AssertionError(f"unexpected reply: {request}")


@dataclass
class FakeExecutor:
    repository: PullRequestJobRepository
    abandoned: list[str] = field(default_factory=list)
    retried: list[str] = field(default_factory=list)
    retry_sources: list[str] = field(default_factory=list)
    scheduled: list[str] = field(default_factory=list)

    def accept(self, request: PullRequestJobRequest) -> PullRequestJob:
        return self.repository.submit(request)

    def accept_retry(self, previous: PullRequestJob, request: PullRequestJobRequest) -> PullRequestJob:
        return self.repository.retry(previous, request)

    def schedule_accepted(self, job_id: str) -> None:
        self.scheduled.append(job_id)

    def submit(self, request: PullRequestJobRequest) -> PullRequestJob:
        return self.repository.submit(request)

    def retry(self, previous: PullRequestJob, request: PullRequestJobRequest) -> PullRequestJob:
        job = self.repository.retry(previous, request)
        self.retried.append(job.id)
        self.retry_sources.append(previous.id)
        return job

    def get(self, job_id: str) -> PullRequestJob:
        return self.repository.get(job_id)

    def reusable(self, candidate_ids: tuple[str, ...]) -> PullRequestJob | None:
        candidates = (self.repository.get(job_id) for job_id in candidate_ids)
        return next((job for job in candidates if job.state is PullRequestJobState.COMPLETED), None)

    def abandon(self, job_id: str, reason: str) -> None:
        self.abandoned.append(job_id)
        self.repository.fail(job_id, reason)


@pytest.mark.asyncio
async def test_observations_are_ingested_before_task_work_is_scheduled(tmp_path: Path) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "control.sqlite")
    metadata.create_all(engine)
    control = PullRequestJobRepository(engine)
    tasks = TaskRepository(engine)
    source = FakeSource(
        True,
        ThreadObservations(
            root=[
                ThreadObservation(
                    source_id="github:owner/repo:5",
                    configured_repository="repo",
                    title="Make the change",
                    eligible=True,
                    messages=ObservedMessages(
                        root=[
                            ObservedMessage(
                                source_id="github:owner/repo:issue:5",
                                actor=GitHubLogin("alice"),
                                classification=MessageClassification.ACTIONABLE,
                                body="Issue body",
                                source_created_at="2026-01-01T00:00:00Z",
                            )
                        ]
                    ),
                )
            ]
        ),
    )
    coordinator = TaskCoordinator(source, tasks, FakeExecutor(control))

    # WHEN
    unresolved = await coordinator.reconcile()

    # THEN
    thread = tasks.threads()[0]
    task = tasks.unresolved(thread.id)
    assert unresolved
    assert thread.configured_repository == "repo"
    assert thread.eligible
    assert tasks.messages(thread.id)[0].body == "Issue body"
    assert task is not None
    job = control.get(tasks.latest_job_id(task.id))
    assert isinstance(job.origin, ThreadOrigin)
    assert job.title == "ocint: Make the change"
    assert job.origin.source_thread_id == thread.source_id
    assert job.origin.source_anchor_id == "github:owner/repo:issue:5"
    engine.dispose()


@pytest.mark.asyncio
async def test_ineligible_queued_job_is_abandoned_and_task_is_skipped(tmp_path: Path) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "control.sqlite")
    metadata.create_all(engine)
    control = PullRequestJobRepository(engine)
    tasks = TaskRepository(engine)
    thread = tasks.upsert_thread("github:owner/repo:5", "Title", "repo", False)
    tasks.upsert_message(
        thread.id,
        "github:owner/repo:issue:5",
        "alice",
        MessageClassification.ACTIONABLE,
        "body",
        "2026-01-01T00:00:00Z",
    )
    task = tasks.create_pending(thread.id, TaskKind.INITIAL, 0)
    assert task is not None
    job = control.submit(
        PullRequestJobRequest(
            idempotency_key="job", actor=GitHubLogin("alice"), repository="repo", title="Title", prompt="body"
        )
    )
    tasks.attach_job(task.id, job.id)
    executor = FakeExecutor(control)

    # WHEN
    await TaskCoordinator(FakeSource(False), tasks, executor).reconcile()

    # THEN
    assert executor.abandoned == [job.id]
    assert tasks.get(task.id).state is TaskState.SKIPPED
    engine.dispose()


@pytest.mark.asyncio
async def test_ineligible_running_job_remains_current_until_terminal(tmp_path: Path) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "control.sqlite")
    metadata.create_all(engine)
    control = PullRequestJobRepository(engine)
    tasks = TaskRepository(engine)
    thread = tasks.upsert_thread("github:owner/repo:5", "Title", "repo", False)
    tasks.upsert_message(
        thread.id,
        "github:owner/repo:issue:5",
        "alice",
        MessageClassification.ACTIONABLE,
        "body",
        "2026-01-01T00:00:00Z",
    )
    task = tasks.create_pending(thread.id, TaskKind.INITIAL, 0)
    assert task is not None
    job = control.submit(
        PullRequestJobRequest(
            idempotency_key="job", actor=GitHubLogin("alice"), repository="repo", title="Title", prompt="body"
        )
    )
    control.claim(job.id)
    tasks.attach_job(task.id, job.id)
    executor = FakeExecutor(control)
    coordinator = TaskCoordinator(FakeSource(False), tasks, executor)

    # WHEN
    await coordinator.reconcile()

    # THEN
    assert executor.abandoned == []
    assert tasks.get(task.id).state is TaskState.UNRESOLVED

    # WHEN
    control.fail(job.id, "terminal")
    await coordinator.reconcile()

    # THEN
    assert tasks.get(task.id).state is TaskState.SKIPPED
    engine.dispose()


@pytest.mark.asyncio
async def test_competing_stale_reconciliation_schedules_one_successor(tmp_path: Path) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "control.sqlite")
    metadata.create_all(engine)
    control = PullRequestJobRepository(engine)
    tasks = TaskRepository(engine)
    thread = tasks.upsert_thread("github:owner/repo:5", "Title", "repo", True)
    tasks.upsert_message(
        thread.id,
        "github:owner/repo:issue:5",
        "alice",
        MessageClassification.ACTIONABLE,
        "body",
        "2026-01-01T00:00:00Z",
    )
    current = tasks.create_pending(thread.id, TaskKind.INITIAL, 0)
    assert current is not None
    failed = control.submit(
        PullRequestJobRequest(
            idempotency_key="failed", actor=GitHubLogin("alice"), repository="repo", title="Title", prompt="body"
        )
    )
    control.fail(failed.id, "failed")
    tasks.attach_job(current.id, failed.id)
    tasks.upsert_message(
        thread.id,
        "github:owner/repo:comment:10",
        "alice",
        MessageClassification.ACTIONABLE,
        "new",
        "2026-01-01T00:01:00Z",
    )
    executor = FakeExecutor(control)
    first = TaskCoordinator(FakeSource(True), tasks, executor)
    stale = TaskCoordinator(FakeSource(True), tasks, executor)

    # WHEN
    created = await first._reconcile_current(current)
    observed = await stale._reconcile_current(current)

    # THEN
    successor = tasks.latest(thread.id)
    assert successor is not None
    assert successor.id != current.id
    assert successor.state is TaskState.UNRESOLVED
    assert tasks.get(current.id).state is TaskState.SKIPPED
    assert len(executor.retried) == 1
    assert tasks.attempt_count(successor.id) == 1
    assert created is not None
    assert observed is None
    assert tasks.attempt_count(current.id) == 1
    engine.dispose()


@pytest.mark.asyncio
async def test_follow_up_reuses_completed_job_selected_through_gateway(tmp_path: Path) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "control.sqlite")
    metadata.create_all(engine)
    control = PullRequestJobRepository(engine)
    tasks = TaskRepository(engine)
    thread = tasks.upsert_thread("github:owner/repo:5", "Title", "repo", True)
    first_message = tasks.upsert_message(
        thread.id,
        "github:owner/repo:issue:5",
        "alice",
        MessageClassification.ACTIONABLE,
        "first",
        "2026-01-01T00:00:00Z",
    )
    first = tasks.create_pending(thread.id, TaskKind.INITIAL, 0)
    assert first is not None
    completed = control.submit(
        PullRequestJobRequest(
            idempotency_key="completed", actor=first_message.actor, repository="repo", title="Title", prompt="first"
        )
    )
    control.complete(completed.id)
    tasks.attach_job(first.id, completed.id)
    tasks.set_state(first.id, TaskState.ADDRESSED)
    second_message = tasks.upsert_message(
        thread.id,
        "github:owner/repo:comment:6",
        "alice",
        MessageClassification.ACTIONABLE,
        "second",
        "2026-01-01T00:01:00Z",
    )
    second = tasks.create_pending(thread.id, TaskKind.FOLLOW_UP, first.id)
    assert second is not None
    failed = control.submit(
        PullRequestJobRequest(
            idempotency_key="failed", actor=second_message.actor, repository="repo", title="Title", prompt="second"
        )
    )
    control.fail(failed.id, "failed")
    tasks.attach_job(second.id, failed.id)
    tasks.set_state(second.id, TaskState.ADDRESSED)
    tasks.upsert_message(
        thread.id,
        "github:owner/repo:comment:7",
        "alice",
        MessageClassification.ACTIONABLE,
        "third",
        "2026-01-01T00:02:00Z",
    )
    executor = FakeExecutor(control)

    # WHEN
    await TaskCoordinator(FakeSource(True), tasks, executor).reconcile()

    # THEN
    assert executor.retry_sources == [completed.id]
    engine.dispose()
