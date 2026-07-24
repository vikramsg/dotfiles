from pydantic import BaseModel, ConfigDict

from ocint.daemon.models import GitHubLogin, GitRepository


class RepositoryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    git_repository: GitRepository
    github_repository: str
    author_name: str
    author_email: str
    actors: frozenset[GitHubLogin]
    checks: tuple[tuple[str, ...], ...]


class SchedulerPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    capacity: int
    job_timeout_seconds: int
    shutdown_timeout_seconds: int


class PullRequestJobConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    repositories: tuple[RepositoryPolicy, ...]
    scheduler: SchedulerPolicy

    def repository(self, name: str) -> RepositoryPolicy:
        for item in self.repositories:
            if item.git_repository.name == name:
                return item
        raise ValueError(f"repository is not configured: {name}")
