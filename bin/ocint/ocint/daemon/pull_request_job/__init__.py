from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

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


@contextmanager
def open_pull_request_job_store(database_path: Path) -> Iterator[PullRequestJobStore]:
    from ocint.daemon.db import create_daemon_engine
    from ocint.daemon.pull_request_job.repository import PullRequestJobRepository

    engine = create_daemon_engine(database_path)
    try:
        yield PullRequestJobRepository(engine)
    finally:
        engine.dispose()


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
    "create_pull_request_job_runner",
    "open_pull_request_job_store",
]
