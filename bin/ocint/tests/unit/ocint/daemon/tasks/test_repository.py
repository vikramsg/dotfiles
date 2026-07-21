from concurrent.futures import ThreadPoolExecutor
from itertools import repeat
from pathlib import Path

import pytest
from ocint.daemon.db import create_daemon_engine
from ocint.daemon.db.schema import metadata
from ocint.daemon.repository import ControlRepository
from ocint.daemon.service import WorkRequest
from ocint.daemon.tasks.models import (
    FailedTaskRetry,
    MessageClassification,
    RetryAttachment,
    SuccessorCreated,
    SuccessorExisting,
    TaskKind,
    TaskState,
)
from ocint.daemon.tasks.repository import TaskRepository


@pytest.fixture
def repository(tmp_path: Path) -> TaskRepository:
    engine = create_daemon_engine(tmp_path / "control.sqlite")
    metadata.create_all(engine)
    return TaskRepository(engine)


def test_pending_is_actionable_and_not_covered_by_unresolved_or_addressed(repository: TaskRepository) -> None:
    # GIVEN
    thread = repository.upsert_thread("github:owner/repo:5", "Title")
    first = repository.upsert_message(
        thread.id, "1", "alice", MessageClassification.ACTIONABLE, "first", "2026-01-01T00:00:00Z"
    )
    repository.upsert_message(
        thread.id, "2", "mallory", MessageClassification.UNAUTHORIZED, "unauthorized", "2026-01-01T00:01:00Z"
    )
    task = repository.create_pending(thread.id, TaskKind.INITIAL, 0)
    assert task is not None

    # WHEN / THEN
    assert repository.pending_messages(thread.id) == ()
    repository.set_state(task.id, TaskState.ADDRESSED)
    assert repository.pending_messages(thread.id) == ()
    assert repository.task_messages(task.id) == (first,)


@pytest.mark.parametrize("state", [TaskState.SKIPPED, TaskState.REJECTED, TaskState.ERRORED])
def test_noncovering_task_states_release_messages(repository: TaskRepository, state: TaskState) -> None:
    # GIVEN
    thread = repository.upsert_thread("github:owner/repo:5", "Title")
    message = repository.upsert_message(
        thread.id, "1", "alice", MessageClassification.ACTIONABLE, "first", "2026-01-01T00:00:00Z"
    )
    task = repository.create_pending(thread.id, TaskKind.INITIAL, 0)
    assert task is not None

    # WHEN
    repository.set_state(task.id, state)

    # THEN
    assert repository.pending_messages(thread.id) == (message,)


def test_create_pending_atomically_attaches_every_pending_message(repository: TaskRepository) -> None:
    # GIVEN
    thread = repository.upsert_thread("github:owner/repo:5", "Title")
    first = repository.upsert_message(
        thread.id, "1", "alice", MessageClassification.ACTIONABLE, "first", "2026-01-01T00:00:00Z"
    )
    second = repository.upsert_message(
        thread.id, "2", "bob", MessageClassification.ACTIONABLE, "second", "2026-01-01T00:01:00Z"
    )

    # WHEN
    task = repository.create_pending(thread.id, TaskKind.INITIAL, 0)

    # THEN
    assert task is not None
    assert repository.task_messages(task.id) == (first, second)
    assert repository.pending_messages(thread.id) == ()


def test_unaddressed_edits_update_in_place_without_becoming_pending(repository: TaskRepository) -> None:
    # GIVEN
    thread = repository.upsert_thread("github:owner/repo:5", "Title")
    repository.upsert_message(
        thread.id, "1", "alice", MessageClassification.ACTIONABLE, "first", "2026-01-01T00:00:00Z"
    )
    task = repository.create_pending(thread.id, TaskKind.INITIAL, 0)
    assert task is not None

    # WHEN
    edited = repository.upsert_message(
        thread.id, "1", "alice", MessageClassification.ACTIONABLE, "edited", "2026-01-01T00:00:00Z"
    )

    # THEN
    assert edited.body == "edited"
    assert repository.pending_messages(thread.id) == ()


def test_addressed_edits_do_not_change_stored_content(repository: TaskRepository) -> None:
    # GIVEN
    thread = repository.upsert_thread("github:owner/repo:5", "Title")
    original = repository.upsert_message(
        thread.id, "1", "alice", MessageClassification.ACTIONABLE, "first", "2026-01-01T00:00:00Z"
    )
    task = repository.create_pending(thread.id, TaskKind.INITIAL, 0)
    assert task is not None
    repository.set_state(task.id, TaskState.ADDRESSED)

    # WHEN
    stored = repository.upsert_message(
        thread.id, "1", "alice", MessageClassification.UNAUTHORIZED, "edited", "2026-01-01T00:00:00Z"
    )

    # THEN
    assert stored == original


def test_failed_successor_rebatches_skipped_task_and_new_messages(repository: TaskRepository) -> None:
    # GIVEN
    thread = repository.upsert_thread("github:owner/repo:5", "Title")
    first = repository.upsert_message(
        thread.id, "1", "alice", MessageClassification.ACTIONABLE, "first", "2026-01-01T00:00:00Z"
    )
    current = repository.create_pending(thread.id, TaskKind.INITIAL, 0)
    assert current is not None
    second = repository.upsert_message(
        thread.id, "2", "alice", MessageClassification.ACTIONABLE, "second", "2026-01-01T00:01:00Z"
    )

    # WHEN
    claim = repository.claim_failed(current, "superseded")

    # THEN
    assert isinstance(claim, SuccessorCreated)
    assert repository.get(current.id).state is TaskState.SKIPPED
    assert repository.task_messages(claim.task.id) == (first, second)


def test_competing_pending_claims_create_one_unresolved_task(repository: TaskRepository) -> None:
    # GIVEN
    thread = repository.upsert_thread("github:owner/repo:5", "Title")
    message = repository.upsert_message(
        thread.id,
        "github:owner/repo:issue:5",
        "alice",
        MessageClassification.ACTIONABLE,
        "first",
        "2026-01-01T00:00:00Z",
    )

    # WHEN
    with ThreadPoolExecutor(max_workers=2) as workers:
        claimed = tuple(
            workers.map(
                repository.create_pending,
                repeat(thread.id, 2),
                repeat(TaskKind.INITIAL, 2),
                repeat(0, 2),
            )
        )

    # THEN
    tasks = tuple(item for item in claimed if item is not None)
    assert len(tasks) == 1
    assert repository.task_messages(tasks[0].id) == (message,)
    assert repository.pending_messages(thread.id) == ()


def test_message_source_identity_is_global(repository: TaskRepository) -> None:
    # GIVEN
    first = repository.upsert_thread("github:owner/repo:5", "First")
    second = repository.upsert_thread("github:owner/repo:6", "Second")
    repository.upsert_message(
        first.id,
        "github:owner/repo:comment:10",
        "alice",
        MessageClassification.ACTIONABLE,
        "first",
        "2026-01-01T00:00:00Z",
    )

    # WHEN / THEN
    with pytest.raises(ValueError, match="already belongs to thread"):
        repository.upsert_message(
            second.id,
            "github:owner/repo:comment:10",
            "alice",
            MessageClassification.ACTIONABLE,
            "second",
            "2026-01-01T00:01:00Z",
        )


def test_competing_stale_successor_claims_return_one_successor(repository: TaskRepository) -> None:
    # GIVEN
    thread = repository.upsert_thread("github:owner/repo:5", "Title")
    first = repository.upsert_message(
        thread.id,
        "github:owner/repo:issue:5",
        "alice",
        MessageClassification.ACTIONABLE,
        "first",
        "2026-01-01T00:00:00Z",
    )
    current = repository.create_pending(thread.id, TaskKind.INITIAL, 0)
    assert current is not None
    second = repository.upsert_message(
        thread.id,
        "github:owner/repo:comment:10",
        "alice",
        MessageClassification.ACTIONABLE,
        "second",
        "2026-01-01T00:01:00Z",
    )

    # WHEN
    with ThreadPoolExecutor(max_workers=2) as workers:
        claims = tuple(
            workers.map(
                repository.claim_failed,
                repeat(current, 2),
                repeat("superseded", 2),
            )
        )

    # THEN
    created = tuple(claim for claim in claims if isinstance(claim, SuccessorCreated))
    existing = tuple(claim for claim in claims if isinstance(claim, SuccessorExisting))
    assert len(created) == 1
    assert len(existing) == 1
    assert created[0].task.id == existing[0].task.id
    assert repository.task_messages(created[0].task.id) == (first, second)


def test_successor_claim_does_not_create_an_empty_task(repository: TaskRepository) -> None:
    # GIVEN
    thread = repository.upsert_thread("github:owner/repo:5", "Title")
    repository.upsert_message(
        thread.id,
        "github:owner/repo:issue:5",
        "alice",
        MessageClassification.ACTIONABLE,
        "first",
        "2026-01-01T00:00:00Z",
    )
    current = repository.create_pending(thread.id, TaskKind.INITIAL, 0)
    assert current is not None
    repository.upsert_message(
        thread.id,
        "github:owner/repo:issue:5",
        "alice",
        MessageClassification.UNAUTHORIZED,
        "first",
        "2026-01-01T00:00:00Z",
    )

    # WHEN
    claim = repository.claim_failed(current, "superseded")

    # THEN
    assert isinstance(claim, FailedTaskRetry)
    assert repository.get(current.id).state is TaskState.UNRESOLVED
    latest = repository.latest(thread.id)
    assert latest is not None
    assert latest.id == current.id


def test_competing_retry_claims_attach_one_durable_attempt(repository: TaskRepository) -> None:
    # GIVEN
    control = ControlRepository(repository.engine)
    thread = repository.upsert_thread("github:owner/repo:5", "Title")
    repository.upsert_message(
        thread.id,
        "github:owner/repo:issue:5",
        "alice",
        MessageClassification.ACTIONABLE,
        "first",
        "2026-01-01T00:00:00Z",
    )
    current = repository.create_pending(thread.id, TaskKind.INITIAL, 0)
    assert current is not None
    failed = control.submit(WorkRequest(idempotency_key="failed", actor="alice", repository="repo", prompt="first"))
    control.fail(failed.id, "failed")
    repository.attach_job(current.id, failed.id)

    # WHEN
    first = repository.claim_failed(current, "superseded")
    competing = repository.claim_failed(current, "superseded")
    assert isinstance(first, FailedTaskRetry)
    assert isinstance(competing, FailedTaskRetry)
    retry = control.retry(
        failed,
        WorkRequest(idempotency_key="retry", actor="alice", repository="repo", prompt="first"),
    )
    attached = repository.attach_claimed_job(current.id, first.attempt, retry.id)
    observed = repository.attach_claimed_job(current.id, competing.attempt, retry.id)

    # THEN
    assert first.attempt == competing.attempt == 2
    assert attached is RetryAttachment.ATTACHED
    assert observed is RetryAttachment.EXISTING
    assert repository.latest_job_id(current.id) == retry.id
