import pytest
from ocint.daemon.models import ActorIdentity, GitHubLogin, GitRepository, PromptObservation, PublishedPublication
from ocint.daemon.pull_request_job.config import PullRequestJobConfig, RepositoryPolicy, SchedulerPolicy
from ocint.daemon.pull_request_job.models import PullRequestJobRequest, SourcePullRequestJobRequest
from ocint.daemon.pull_request_job.service import PromptDecision, authorize, prompt_action
from pydantic import BaseModel, ValidationError


def test_published_pull_request_requires_positive_number() -> None:
    # GIVEN / WHEN / THEN
    with pytest.raises(ValidationError, match="greater than 0"):
        PublishedPublication(url="https://example.test/pull/1", number=0)


def test_public_request_cannot_claim_source_authorization() -> None:
    # GIVEN
    config = PullRequestJobConfig(
        repositories=(
            RepositoryPolicy(
                git_repository=GitRepository(name="repo", remote_url="git@example.test:repo.git"),
                github_repository="owner/repo",
                author_name="Agent",
                author_email="agent@example.test",
                actors=frozenset((GitHubLogin("maintainer"),)),
                checks=(),
            ),
        ),
        scheduler=SchedulerPolicy(capacity=1, job_timeout_seconds=60, shutdown_timeout_seconds=10),
    )
    direct = PullRequestJobRequest(
        idempotency_key="direct",
        actor=ActorIdentity("slack:u1"),
        repository="repo",
        title="Work",
        prompt="Work",
    )
    # WHEN / THEN
    with pytest.raises(PermissionError):
        authorize(direct, config)
    with pytest.raises(ValidationError, match="authorization"):
        PullRequestJobRequest.model_validate({**direct.model_dump(), "authorization": "source_verified"})
    assert not issubclass(SourcePullRequestJobRequest, BaseModel)


@pytest.mark.parametrize(
    ("observation", "expected"),
    [
        (PromptObservation(found=True, completed=True, active=False), PromptDecision.ADVANCE),
        (PromptObservation(found=True, completed=False, active=True), PromptDecision.WAIT),
        (PromptObservation(found=True, completed=False, active=False), PromptDecision.SUBMIT),
        (PromptObservation(found=False, completed=False, active=False), PromptDecision.SUBMIT),
        (PromptObservation(found=False, completed=False, active=True), PromptDecision.SUBMIT),
    ],
)
def test_prompt_decision_matrix(observation: PromptObservation, expected: PromptDecision) -> None:
    # GIVEN / WHEN
    decision = prompt_action(observation)

    # THEN
    assert decision is expected
