from __future__ import annotations

from typing import TYPE_CHECKING

from ocint.daemon.git.config import GitConfig, GitRuntimeConfig

if TYPE_CHECKING:
    from ocint.daemon.git.service import GitManager


def create_git_manager(config: GitRuntimeConfig) -> GitManager:
    from ocint.daemon.git.service import GitManager

    return GitManager(config)


__all__ = ["GitConfig", "GitRuntimeConfig", "create_git_manager"]
