from __future__ import annotations

from typing import TYPE_CHECKING

from ocint.daemon.models import (
    DirectOrigin,
    PublicationRequest,
    PublicationResult,
    PublishedPublication,
    RefusedPublication,
    ThreadOrigin,
)
from ocint.daemon.pull_request_job.config import PullRequestJobConfig, RepositoryPolicy, SchedulerPolicy
from ocint.daemon.pull_request_job.contracts import (
    GitGateway,
    OpenCodeGateway,
    PullRequestJobRunnerGateway,
    PullRequestJobStore,
    PullRequestPublisher,
)
from ocint.daemon.pull_request_job.models import (
    PullRequestJob,
    PullRequestJobRequest,
    PullRequestJobStage,
    PullRequestJobState,
)

if TYPE_CHECKING:
    from sqlalchemy import Engine


def create_pull_request_job_repository(engine: Engine) -> PullRequestJobStore:
    from ocint.daemon.pull_request_job.repository import PullRequestJobRepository

    return PullRequestJobRepository(engine)


def create_pull_request_job_runner(
    config: PullRequestJobConfig,
    store: PullRequestJobStore,
    opencode: OpenCodeGateway,
    git: GitGateway,
    publisher: PullRequestPublisher,
) -> PullRequestJobRunnerGateway:
    from ocint.daemon.pull_request_job.run import PullRequestJobRunner

    return PullRequestJobRunner(config, store, opencode, git, publisher)


__all__ = [
    "DirectOrigin",
    "PublicationRequest",
    "PublicationResult",
    "PublishedPublication",
    "PullRequestJob",
    "PullRequestJobConfig",
    "PullRequestJobRequest",
    "PullRequestJobRunnerGateway",
    "PullRequestJobStage",
    "PullRequestJobState",
    "PullRequestJobStore",
    "RefusedPublication",
    "RepositoryPolicy",
    "SchedulerPolicy",
    "ThreadOrigin",
    "create_pull_request_job_repository",
    "create_pull_request_job_runner",
]
