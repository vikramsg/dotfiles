from dataclasses import dataclass, field
from pathlib import Path

import pytest
from ocint.daemon.db import create_daemon_engine
from ocint.daemon.db.schema import metadata
from ocint.daemon.models import Job
from ocint.daemon.repository import ControlRepository
from ocint.daemon.service import WorkRequest
from ocint.daemon.tasks.models import MessageClassification, Task, TaskKind, TaskState
from ocint.daemon.tasks.repository import TaskRepository
from ocint.daemon.tasks.run import TaskCoordinator


@dataclass
class FakeSource:
    eligible_state: bool

    async def poll(self) -> None:
        return None

    async def complete_task(self, task: Task, job: Job) -> None:
        _ = (task, job)

    def eligible(self, thread_id: int) -> bool:
        _ = thread_id
        return self.eligible_state

    def configured_repository(self, thread_id: int) -> str:
        _ = thread_id
        return "repo"


@dataclass
class FakeExecutor:
    repository: ControlRepository
    abandoned: list[str] = field(default_factory=list)
    retried: list[str] = field(default_factory=list)
    scheduled: list[str] = field(default_factory=list)

    def accept(self, request: WorkRequest) -> Job:
        return self.repository.submit(request)

    def accept_retry(self, previous: Job, request: WorkRequest) -> Job:
        return self.repository.retry(previous, request)

    def schedule_accepted(self, job_id: str) -> None:
        self.scheduled.append(job_id)

    def submit(self, request: WorkRequest) -> Job:
        return self.repository.submit(request)

    def retry(self, previous: Job, request: WorkRequest) -> Job:
        job = self.repository.retry(previous, request)
        self.retried.append(job.id)
        return job

    def get(self, job_id: str) -> Job:
        return self.repository.get(job_id)

    def abandon(self, job_id: str, reason: str) -> None:
        self.abandoned.append(job_id)
        self.repository.fail(job_id, reason)


@pytest.mark.asyncio
async def test_ineligible_queued_job_is_abandoned_and_task_is_skipped(tmp_path: Path) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "control.sqlite")
    metadata.create_all(engine)
    control = ControlRepository(engine)
    tasks = TaskRepository(engine)
    thread = tasks.upsert_thread("github:owner/repo:5", "Title")
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
    job = control.submit(WorkRequest(idempotency_key="job", actor="alice", repository="repo", prompt="body"))
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
    control = ControlRepository(engine)
    tasks = TaskRepository(engine)
    thread = tasks.upsert_thread("github:owner/repo:5", "Title")
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
    job = control.submit(WorkRequest(idempotency_key="job", actor="alice", repository="repo", prompt="body"))
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
    control = ControlRepository(engine)
    tasks = TaskRepository(engine)
    thread = tasks.upsert_thread("github:owner/repo:5", "Title")
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
    failed = control.submit(WorkRequest(idempotency_key="failed", actor="alice", repository="repo", prompt="body"))
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
