from pathlib import Path

import pytest
from ocint.daemon.db import create_daemon_engine
from ocint.daemon.db.schema import metadata
from ocint.daemon.models import GitHubLogin, JobStage, JobState
from ocint.daemon.repository import ControlRepository
from ocint.daemon.service import (
    CommitCheckpoint,
    PromptIntentCheckpoint,
    PromptSubmittedCheckpoint,
    PullRequestCheckpoint,
    PushCheckpoint,
    SessionCheckpoint,
    StageCheckpoint,
    WorkRequest,
    WorktreeCheckpoint,
)


@pytest.fixture
def repository(tmp_path: Path) -> ControlRepository:
    engine = create_daemon_engine(tmp_path / "control.sqlite")
    metadata.create_all(engine)
    return ControlRepository(engine)


def test_submit_is_idempotent_and_jobs_are_claimed_explicitly(repository: ControlRepository) -> None:
    # GIVEN
    first = repository.submit(
        WorkRequest(idempotency_key="one", actor=GitHubLogin("actor"), repository="repo", title="One", prompt="first")
    )
    duplicate = repository.submit(
        WorkRequest(idempotency_key="one", actor=GitHubLogin("actor"), repository="repo", title="One", prompt="first")
    )
    second = repository.submit(
        WorkRequest(idempotency_key="two", actor=GitHubLogin("actor"), repository="repo", title="Two", prompt="second")
    )

    # WHEN
    claimed = repository.claim(first.id)

    # THEN
    assert duplicate.id == first.id
    assert first.title == "ocint: One"
    assert claimed is not None
    assert claimed.state is JobState.RUNNING
    assert repository.pending_ids() == [second.id]
    assert repository.claim(first.id) is None


def test_retry_preserves_the_requested_work_title(repository: ControlRepository) -> None:
    # GIVEN
    previous = repository.submit(
        WorkRequest(
            idempotency_key="first",
            actor=GitHubLogin("actor"),
            repository="repo",
            title="Human-readable title",
            prompt="first",
        )
    )

    # WHEN
    retried = repository.retry(
        previous,
        WorkRequest(
            idempotency_key="retry",
            actor=GitHubLogin("actor"),
            repository="repo",
            title="Human-readable title",
            prompt="follow-up",
        ),
    )

    # THEN
    assert retried.title == "ocint: Human-readable title"


def test_submit_canonicalizes_an_existing_ocint_title(repository: ControlRepository) -> None:
    # GIVEN / WHEN
    submitted = repository.submit(
        WorkRequest(
            idempotency_key="prefixed",
            actor=GitHubLogin("actor"),
            repository="repo",
            title=" OCINT: Existing title ",
            prompt="work",
        )
    )

    # THEN
    assert submitted.title == "ocint: Existing title"


def test_work_request_rejects_an_empty_ocint_title() -> None:
    # GIVEN / WHEN / THEN
    with pytest.raises(ValueError, match="work title must contain text"):
        WorkRequest(
            idempotency_key="empty-title",
            actor=GitHubLogin("actor"),
            repository="repo",
            title="ocint: ",
            prompt="work",
        )


def test_reconcile_preserves_checkpoint(repository: ControlRepository) -> None:
    # GIVEN
    submitted = repository.submit(
        WorkRequest(idempotency_key="one", actor=GitHubLogin("actor"), repository="repo", title="One", prompt="first")
    )
    repository.claim(submitted.id)
    repository.checkpoint(submitted.id, CommitCheckpoint(sha="abc"))

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
    submitted = repository.submit(
        WorkRequest(idempotency_key="one", actor=GitHubLogin("actor"), repository="repo", title="One", prompt="first")
    )
    repository.claim(submitted.id)
    repository.checkpoint(submitted.id, StageCheckpoint(stage=JobStage.COMMIT))

    # WHEN
    repository.requeue(submitted.id)

    # THEN
    current = repository.get(submitted.id)
    assert current.state is JobState.QUEUED
    assert current.stage is JobStage.COMMIT


def test_push_checkpoint_recovers_stage_and_baseline_atomically(repository: ControlRepository) -> None:
    # GIVEN
    submitted = repository.submit(
        WorkRequest(idempotency_key="one", actor=GitHubLogin("actor"), repository="repo", title="One", prompt="work")
    )
    repository.checkpoint(
        submitted.id, WorktreeCheckpoint(path=Path("/worktree"), branch="ocint/job", base_revision="base")
    )
    repository.checkpoint(submitted.id, CommitCheckpoint(sha="new-commit"))

    # WHEN
    repository.checkpoint(submitted.id, PushCheckpoint(revision="new-commit"))
    recovered = repository.get(submitted.id)

    # THEN
    assert recovered.stage is JobStage.PULL_REQUEST
    assert recovered.pushed
    assert recovered.base_revision == "new-commit"


def test_typed_checkpoints_preserve_paths_and_explicit_terminal_states(
    repository: ControlRepository, tmp_path: Path
) -> None:
    # GIVEN
    submitted = repository.submit(
        WorkRequest(idempotency_key="one", actor=GitHubLogin("actor"), repository="repo", title="One", prompt="first")
    )
    worktree_path = tmp_path / "worktree"

    # WHEN
    repository.checkpoint(
        submitted.id,
        WorktreeCheckpoint(path=worktree_path, branch="ocint/job", base_revision="base"),
    )
    repository.checkpoint(submitted.id, SessionCheckpoint(session_id="session", server_url="http://opencode.test"))
    repository.checkpoint(submitted.id, PromptIntentCheckpoint())
    repository.checkpoint(submitted.id, PromptSubmittedCheckpoint())
    repository.checkpoint(submitted.id, StageCheckpoint(stage=JobStage.COMMIT))
    repository.checkpoint(submitted.id, CommitCheckpoint(sha="commit"))
    pushed = repository.checkpoint(submitted.id, PushCheckpoint(revision="commit"))
    repository.checkpoint(submitted.id, PullRequestCheckpoint(url="https://example.test/pull/1"))
    completed = repository.complete(submitted.id)

    failed_job = repository.submit(
        WorkRequest(idempotency_key="two", actor=GitHubLogin("actor"), repository="repo", title="Two", prompt="second")
    )
    failed = repository.fail(failed_job.id, "failed safely")

    # THEN
    assert completed.worktree_path == worktree_path
    assert isinstance(completed.worktree_path, Path)
    assert completed.session_id == "session"
    assert completed.prompt_intended
    assert completed.prompt_submitted
    assert completed.commit_sha == "commit"
    assert completed.base_revision == "commit"
    assert completed.pushed
    assert pushed.stage is JobStage.PULL_REQUEST
    assert pushed.base_revision == "commit"
    assert completed.pull_request_url == "https://example.test/pull/1"
    assert completed.state is JobState.COMPLETED
    assert completed.stage is JobStage.COMPLETE
    assert failed.state is JobState.FAILED
    assert failed.error == "failed safely"
