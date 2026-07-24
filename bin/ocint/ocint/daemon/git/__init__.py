from typing import Protocol

from ocint.daemon.git.config import GitConfig, GitRuntimeConfig
from ocint.daemon.models import GitRepository, Worktree


class GitGateway(Protocol):
    async def provision(self, repository: GitRepository, job_id: str) -> Worktree: ...
    async def validate(self, worktree: Worktree, checks: tuple[tuple[str, ...], ...]) -> None: ...
    async def commit(self, worktree: Worktree, message: str, author_name: str, author_email: str) -> str: ...
    async def push(self, worktree: Worktree) -> None: ...


def create_git_manager(config: GitRuntimeConfig) -> GitGateway:
    from ocint.daemon.git.service import GitManager

    return GitManager(config)


__all__ = ["GitConfig", "GitGateway", "GitRuntimeConfig", "create_git_manager"]
