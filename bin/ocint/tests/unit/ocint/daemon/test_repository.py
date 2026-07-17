from pathlib import Path

import pytest
from ocint.daemon.db import create_daemon_engine
from ocint.daemon.db.schema import metadata
from ocint.daemon.repository import ControlRepository
from ocint.daemon.service import JobStage, JobState, WorkRequest


@pytest.fixture
def repository(tmp_path: Path) -> ControlRepository:
    engine = create_daemon_engine(tmp_path / "control.sqlite")
    metadata.create_all(engine)
    return ControlRepository(engine)


def test_submit_is_idempotent_and_jobs_are_claimed_explicitly(repository: ControlRepository) -> None:
    # GIVEN
    first = repository.submit(WorkRequest(idempotency_key="one", actor="actor", repository="repo", prompt="first"))
    duplicate = repository.submit(WorkRequest(idempotency_key="one", actor="actor", repository="repo", prompt="first"))
    second = repository.submit(WorkRequest(idempotency_key="two", actor="actor", repository="repo", prompt="second"))

    # WHEN
    claimed = repository.claim(first.id)

    # THEN
    assert duplicate.id == first.id
    assert claimed is not None
    assert claimed.state is JobState.RUNNING
    assert repository.pending_ids() == [second.id]
    assert repository.claim(first.id) is None


def test_reconcile_preserves_checkpoint(repository: ControlRepository) -> None:
    # GIVEN
    submitted = repository.submit(WorkRequest(idempotency_key="one", actor="actor", repository="repo", prompt="first"))
    repository.claim(submitted.id)
    repository.checkpoint(submitted.id, JobStage.PUSH, commit_sha="abc")

    # WHEN
    count = repository.reconcile()
    reconciled = repository.get(submitted.id)

    # THEN
    assert count == 1
    assert reconciled.state is JobState.QUEUED
    assert reconciled.stage is JobStage.PUSH
    assert reconciled.commit_sha == "abc"


def test_requeue_retains_stage_for_shutdown_resume(repository: ControlRepository) -> None:
    # GIVEN
    submitted = repository.submit(WorkRequest(idempotency_key="one", actor="actor", repository="repo", prompt="first"))
    repository.claim(submitted.id)
    repository.checkpoint(submitted.id, JobStage.COMMIT, base_revision="base")

    # WHEN
    repository.requeue(submitted.id)

    # THEN
    current = repository.get(submitted.id)
    assert current.state is JobState.QUEUED
    assert current.stage is JobStage.COMMIT
