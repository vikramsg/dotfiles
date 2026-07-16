import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from ocint.daemon.config import DaemonConfig, RepositoryConfig
from ocint.daemon.db import create_daemon_engine, migrate_daemon_db
from ocint.daemon.models import Claim, Job, JobStage, JobState, PromptObservation, WorkRequest, WorkSource, Worktree
from ocint.daemon.repository import ControlRepository
from ocint.daemon.service import accept_work, build_follow_up, recovery_plan, retirable_workspaces, terminal_update
from ocint.daemon.workspace_repository import WorkspaceRepository


def test_recovery_resets_dead_prompt_when_opencode_restarted_without_changes() -> None:
    # GIVEN an interrupted execution with a persisted prompt but no active OpenCode runner or changes
    job = Job(
        id="job",
        idempotency_key="delivery",
        conversation_id="conversation",
        actor="actor",
        repository="repo",
        prompt="change",
        source=WorkSource.MANUAL,
        delivery_adapter="manual",
        delivery_target="manual",
        parent_job_id="",
        workspace_owner_id="job",
        state=JobState.RUNNING,
        stage=JobStage.EXECUTION,
        priority=0,
        attempt_count=1,
        session_id="ses_old",
        worktree_path=Path("/tmp/worktree"),
        branch="ocint/job",
        base_revision="abc",
        prompt_intended=True,
        prompt_submitted=True,
        commit_sha="",
        pushed=False,
        pull_request_url="",
        cancel_requested=False,
        server_url="http://127.0.0.1:4096",
        error="",
        created_at=datetime(2026, 7, 16, tzinfo=UTC),
        updated_at=datetime(2026, 7, 16, tzinfo=UTC),
    )
    claim = Claim(job=job, attempt_id="attempt", lease_id="lease")

    # WHEN recovery observes an idle persisted session and unchanged worktree
    plan = recovery_plan(claim, "idle", PromptObservation(found=True, completed=False), False, 3)

    # THEN it starts a fresh deterministic attempt instead of waiting for a nonexistent event or duplicating in-session
    assert plan.state is JobState.QUEUED
    assert plan.stage is JobStage.EXECUTION
    assert plan.reset_execution is True


def test_recovery_completed_prompt_at_max_attempts_one_advances_to_validation() -> None:
    # GIVEN max_attempts=1, submission intent, a persisted completed prompt, and a crash before checkpoint
    job = Job(
        id="job",
        idempotency_key="delivery",
        conversation_id="conversation",
        actor="actor",
        repository="repo",
        prompt="change",
        source=WorkSource.MANUAL,
        delivery_adapter="manual",
        delivery_target="manual",
        parent_job_id="",
        workspace_owner_id="job",
        state=JobState.RUNNING,
        stage=JobStage.EXECUTION,
        priority=0,
        attempt_count=1,
        session_id="ses_old",
        worktree_path=Path("/tmp/worktree"),
        branch="ocint/job",
        base_revision="abc",
        prompt_intended=True,
        prompt_submitted=False,
        commit_sha="",
        pushed=False,
        pull_request_url="",
        cancel_requested=False,
        server_url="http://127.0.0.1:4096",
        error="",
        created_at=datetime(2026, 7, 16, tzinfo=UTC),
        updated_at=datetime(2026, 7, 16, tzinfo=UTC),
    )
    claim = Claim(job=job, attempt_id="attempt", lease_id="lease")

    # WHEN recovery finds the completed prompt and edits produced before the runner disappeared
    plan = recovery_plan(claim, "idle", PromptObservation(found=True, completed=True), True, 1)

    # THEN it resumes at validation without sending the prompt again
    assert plan.stage is JobStage.VALIDATION
    assert plan.state is JobState.QUEUED
    assert plan.reset_execution is False


def test_linked_followups_share_one_workspace_retirement_lifecycle(tmp_path: Path) -> None:
    # GIVEN a completed root job and linked follow-up sharing its retained workspace/session
    path = tmp_path / "control.sqlite"
    migrate_daemon_db(path)
    engine = create_daemon_engine(path)
    repository = ControlRepository(engine)
    config = DaemonConfig(
        database_path=path,
        mirror_root=tmp_path / "mirrors",
        worktree_root=tmp_path / "worktrees",
        repositories=[RepositoryConfig(name="repo", remote_url="file:///remote", actors=frozenset(["actor"]))],
    )
    root = accept_work(
        WorkRequest(
            idempotency_key="root",
            conversation_id="conversation",
            actor="actor",
            repository="repo",
            text="root change",
            source=WorkSource.MANUAL,
            delivery_adapter="manual",
            delivery_target="manual",
        ),
        config,
        repository,
    )
    root_claim = repository.claim("runner", 1, 60, "{}")
    assert root_claim is not None
    worktree = Worktree(path=tmp_path / "worktree", branch="ocint/root", base_revision="base")
    repository.set_worktree(root.id, root_claim.lease_id, worktree)
    repository.set_session(root.id, root_claim.lease_id, "ses_shared", "http://127.0.0.1:4096")
    current_root = repository.get(root.id)
    repository.finish_with_outbox(
        root_claim,
        JobState.COMPLETED,
        "",
        terminal_update(current_root, JobState.COMPLETED, "completed"),
    )
    follow = accept_work(build_follow_up(repository.get(root.id), "continue", "follow"), config, repository)

    # WHEN retention runs while the child is active, then after it completes
    assert retirable_workspaces(repository, 0) == []
    follow_claim = repository.claim("runner", 1, 60, "{}")
    assert follow_claim is not None
    repository.finish_with_outbox(
        follow_claim,
        JobState.COMPLETED,
        "",
        terminal_update(follow, JobState.COMPLETED, "completed"),
    )
    eligible = retirable_workspaces(repository, 0)

    # THEN exactly one owner retires and all linked rows lose the workspace together
    assert [item.id for item in eligible] == [root.id]
    workspaces = WorkspaceRepository(engine)
    retirement = workspaces.claim_retirement(root.workspace_owner_id, str(worktree.path), "runner-a", 60)
    assert retirement is not None
    assert workspaces.claim_retirement(root.workspace_owner_id, str(worktree.path), "runner-b", 60) is None
    assert workspaces.complete(retirement, "transient failure")
    dispose_crash = workspaces.claim_retirement(root.workspace_owner_id, str(worktree.path), "runner-b", -1)
    assert dispose_crash is not None
    removal_crash = workspaces.claim_retirement(root.workspace_owner_id, str(worktree.path), "runner-c", 1)
    assert removal_crash is not None
    assert workspaces.complete(dispose_crash) is False
    assert workspaces.checkpoint(removal_crash, disposed=True, removed=False)
    time.sleep(1.1)
    replacement = workspaces.claim_retirement(root.workspace_owner_id, str(worktree.path), "runner-d", 60)
    assert replacement is not None
    assert replacement.disposed is True
    assert replacement.removed is False
    with pytest.raises(ValueError, match="continuation precondition"):
        accept_work(build_follow_up(repository.get(root.id), "too late", "late-follow"), config, repository)
    assert workspaces.checkpoint(replacement, disposed=True, removed=True)
    assert workspaces.complete(replacement)
    assert repository.get(root.id).worktree_path is None
    assert repository.get(follow.id).worktree_path is None
    assert [item.kind for item in repository.artifacts(root.id)].count("retired_worktree") == 1
    assert retirable_workspaces(repository, 0) == []
    engine.dispose()
