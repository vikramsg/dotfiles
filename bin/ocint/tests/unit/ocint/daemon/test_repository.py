from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from ocint.daemon.db import create_daemon_engine, migrate_daemon_db
from ocint.daemon.models import JobState, WorkRequest, WorkSource, Worktree
from ocint.daemon.outbox_repository import OutboxRepository
from ocint.daemon.repository import ControlRepository
from ocint.daemon.runner_repository import RunnerRepository
from ocint.daemon.service import cancel_job, retry_job, terminal_update


def test_submit_is_durable_and_idempotent(tmp_path: Path) -> None:
    # GIVEN a migrated independent control database and one manual request
    path = tmp_path / "control.sqlite"
    migrate_daemon_db(path)
    engine = create_daemon_engine(path)
    repository = ControlRepository(engine)
    request = WorkRequest(
        idempotency_key="delivery-1",
        conversation_id="manual-1",
        actor="actor",
        repository="repo",
        text="change documentation",
        source=WorkSource.MANUAL,
        delivery_adapter="manual",
        delivery_target="manual",
    )

    # WHEN the same delivery is submitted twice
    first = repository.submit(request)
    second = repository.submit(request)

    # THEN one durable queued job represents both deliveries
    assert first.id == second.id
    assert repository.get(first.id).state is JobState.QUEUED
    assert len(repository.list()) == 1
    assert OutboxRepository(engine).claim("outbox-runner", 30)[0].delivery_target == "manual"
    engine.dispose()


def test_claim_enforces_capacity_atomically(tmp_path: Path) -> None:
    # GIVEN two queued jobs in a migrated SQLite database
    path = tmp_path / "control.sqlite"
    migrate_daemon_db(path)
    engine = create_daemon_engine(path)
    repository = ControlRepository(engine)
    for number in range(2):
        repository.submit(
            WorkRequest(
                idempotency_key=f"delivery-{number}",
                conversation_id=f"manual-{number}",
                actor="actor",
                repository="repo",
                text="change documentation",
                source=WorkSource.MANUAL,
                delivery_adapter="manual",
                delivery_target="manual",
            )
        )

    # WHEN two claims compete for one configured slot
    first = repository.claim("worker", 1, 60, "{}")
    second = repository.claim("worker", 1, 60, "{}")

    # THEN exactly one durable lease is admitted
    assert first is not None
    assert second is None
    engine.dispose()


def test_restart_reconciliation_requeues_an_expired_attempt(tmp_path: Path) -> None:
    # GIVEN an active attempt whose durable lease expired before restart
    path = tmp_path / "control.sqlite"
    migrate_daemon_db(path)
    engine = create_daemon_engine(path)
    repository = ControlRepository(engine)
    runners = RunnerRepository(engine, repository)
    runners.register("runner-a", 60)
    job = repository.submit(
        WorkRequest(
            idempotency_key="delivery-expired",
            conversation_id="manual-expired",
            actor="actor",
            repository="repo",
            text="change documentation",
            source=WorkSource.MANUAL,
            delivery_adapter="manual",
            delivery_target="manual",
        )
    )
    claim = repository.claim("old-worker", 1, -1, "{}")

    # WHEN a new process reconciles expired leases under a two-attempt policy
    interrupted = runners.recoverable("new-worker")
    recovered = runners.recover(
        interrupted[0],
        JobState.QUEUED,
        interrupted[0].job.stage,
        "expired",
        reset_execution=False,
    )

    # THEN the interrupted attempt releases capacity and is safely queued again
    assert claim is not None
    assert recovered is not None
    assert recovered.id == job.id
    assert repository.get(job.id).state is JobState.QUEUED
    engine.dispose()


def test_expired_lease_cannot_mutate_active_job(tmp_path: Path) -> None:
    # GIVEN a claimed job whose fencing lease has expired
    path = tmp_path / "control.sqlite"
    migrate_daemon_db(path)
    engine = create_daemon_engine(path)
    repository = ControlRepository(engine)
    repository.submit(
        WorkRequest(
            idempotency_key="delivery-fenced",
            conversation_id="manual-fenced",
            actor="actor",
            repository="repo",
            text="change documentation",
            source=WorkSource.MANUAL,
            delivery_adapter="manual",
            delivery_target="manual",
        )
    )
    claim = repository.claim("worker", 1, -1, "{}")
    assert claim is not None

    # WHEN the stale worker attempts an active checkpoint mutation
    with pytest.raises(RuntimeError, match="lease lost"):
        repository.set_worktree(
            claim.job.id,
            claim.lease_id,
            Worktree(path=tmp_path / "worktree", branch="ocint/fenced", base_revision="abc"),
        )

    # THEN durable job state remains unchanged
    assert repository.get(claim.job.id).worktree_path is None
    engine.dispose()


def test_queued_cancel_is_terminal_and_explicit_retry_requeues_it(tmp_path: Path) -> None:
    # GIVEN a queued durable job
    path = tmp_path / "control.sqlite"
    migrate_daemon_db(path)
    engine = create_daemon_engine(path)
    repository = ControlRepository(engine)
    job = repository.submit(
        WorkRequest(
            idempotency_key="delivery-cancel",
            conversation_id="manual-cancel",
            actor="actor",
            repository="repo",
            text="change documentation",
            source=WorkSource.MANUAL,
            delivery_adapter="manual",
            delivery_target="manual",
        )
    )

    # WHEN cancellation and retry actions are applied
    cancelled = cancel_job(repository, job.id)
    retried = retry_job(repository, job.id)

    # THEN cancellation cannot leave an unclaimable queued job and retry is explicit
    assert cancelled.state is JobState.CANCELLED
    assert retried.state is JobState.QUEUED
    assert retried.cancel_requested is False
    terminal_deliveries = OutboxRepository(engine).claim("outbox-runner", 30)
    assert [item.update.status for item in terminal_deliveries] == [JobState.QUEUED, JobState.CANCELLED]
    engine.dispose()


def test_concurrent_claims_admit_only_configured_capacity(tmp_path: Path) -> None:
    # GIVEN two queued jobs and two independent workers sharing one SQLite control database
    path = tmp_path / "control.sqlite"
    migrate_daemon_db(path)
    engine = create_daemon_engine(path)
    repository = ControlRepository(engine)
    RunnerRepository(engine, repository).register("runner-a", 60)
    for number in range(2):
        repository.submit(
            WorkRequest(
                idempotency_key=f"concurrent-{number}",
                conversation_id=f"manual-{number}",
                actor="actor",
                repository="repo",
                text="change documentation",
                source=WorkSource.MANUAL,
                delivery_adapter="manual",
                delivery_target="manual",
            )
        )

    # WHEN both workers claim concurrently at capacity one
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(repository.claim, "runner-a", 1, 60, "{}")
        second = executor.submit(repository.claim, "runner-b", 1, 60, "{}")
        claims = [first.result(), second.result()]

    # THEN BEGIN IMMEDIATE and durable leases admit exactly one
    assert sum(claim is not None for claim in claims) == 1
    engine.dispose()


def test_second_runner_never_recovers_an_unexpired_foreign_lease(tmp_path: Path) -> None:
    # GIVEN runner A owns an unexpired active lease
    path = tmp_path / "control.sqlite"
    migrate_daemon_db(path)
    engine = create_daemon_engine(path)
    repository = ControlRepository(engine)
    runners = RunnerRepository(engine, repository)
    runners.register("runner-a", 60)
    job = repository.submit(
        WorkRequest(
            idempotency_key="foreign-lease",
            conversation_id="manual-foreign",
            actor="actor",
            repository="repo",
            text="change documentation",
            source=WorkSource.MANUAL,
            delivery_adapter="manual",
            delivery_target="manual",
        )
    )
    claim = repository.claim("runner-a", 1, 60, "{}")
    assert claim is not None

    # WHEN runner B performs startup recovery
    interrupted = runners.recoverable("runner-b")

    # THEN it cannot take or release runner A's live lease
    assert interrupted == []
    assert repository.get(job.id).state is JobState.PREPARING
    assert repository.heartbeat(claim.lease_id, 60)
    engine.dispose()


def test_concurrent_outbox_claims_are_fenced_to_one_runner(tmp_path: Path) -> None:
    # GIVEN one pending durable outbound delivery
    path = tmp_path / "control.sqlite"
    migrate_daemon_db(path)
    engine = create_daemon_engine(path)
    repository = ControlRepository(engine)
    repository.submit(
        WorkRequest(
            idempotency_key="outbox-concurrent",
            conversation_id="manual-outbox",
            actor="actor",
            repository="repo",
            text="change documentation",
            source=WorkSource.MANUAL,
            delivery_adapter="manual",
            delivery_target="manual",
        )
    )

    # WHEN two daemon runners claim the outbox concurrently
    with ThreadPoolExecutor(max_workers=2) as executor:
        outbox = OutboxRepository(engine)
        first = executor.submit(outbox.claim, "runner-a", 30)
        second = executor.submit(outbox.claim, "runner-b", 30)
        claims = [*first.result(), *second.result()]

    # THEN exactly one fenced delivery lease exists and only its token can complete it
    assert len(claims) == 1
    item = claims[0]
    assert outbox.acknowledge(item.id, "wrong-token") is False
    assert outbox.acknowledge(item.id, item.lease_id) is True
    assert outbox.claim("runner-c", 30) == []
    engine.dispose()


def test_failed_terminal_state_enqueues_exact_target_update(tmp_path: Path) -> None:
    # GIVEN an active job with an exact manual adapter destination
    path = tmp_path / "control.sqlite"
    migrate_daemon_db(path)
    engine = create_daemon_engine(path)
    repository = ControlRepository(engine)
    job = repository.submit(
        WorkRequest(
            idempotency_key="failed-terminal",
            conversation_id="manual-failed",
            actor="actor",
            repository="repo",
            text="change documentation",
            source=WorkSource.MANUAL,
            delivery_adapter="manual",
            delivery_target="manual",
        )
    )
    claim = repository.claim("runner", 1, 60, "{}")
    assert claim is not None

    # WHEN execution reaches terminal failure
    repository.finish_with_outbox(
        claim,
        JobState.FAILED,
        "failed",
        terminal_update(job, JobState.FAILED, "failed"),
    )
    deliveries = OutboxRepository(engine).claim("outbox-runner", 30)

    # THEN accepted and failed updates retain the exact adapter and destination
    assert [item.update.status for item in deliveries] == [JobState.QUEUED, JobState.FAILED]
    assert all(item.delivery_adapter == "manual" for item in deliveries)
    assert all(item.delivery_target == "manual" for item in deliveries)
    engine.dispose()
