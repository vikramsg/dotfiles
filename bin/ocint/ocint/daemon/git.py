import asyncio
import os
import re
from collections.abc import Mapping
from pathlib import Path

from ocint.daemon.config import RepositoryConfig
from ocint.daemon.service import Worktree


class GitManager:
    def __init__(
        self,
        mirror_root: Path,
        worktree_root: Path,
        validation_environment: Mapping[str, str],
        git_environment: Mapping[str, str],
        timeout_seconds: int,
        output_bytes: int,
    ) -> None:
        self.mirror_root = mirror_root.resolve()
        self.worktree_root = worktree_root.resolve()
        self.validation_environment = dict(validation_environment)
        self.git_environment = dict(git_environment)
        self.timeout_seconds = timeout_seconds
        self.output_bytes = output_bytes

    async def provision(self, repository: RepositoryConfig, job_id: str) -> Worktree:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", repository.name):
            raise ValueError(f"unsafe repository name: {repository.name}")
        self.mirror_root.mkdir(parents=True, exist_ok=True)
        self.worktree_root.mkdir(parents=True, exist_ok=True)
        mirror = self.mirror_root / f"{repository.name}.git"
        worktree = self.worktree_root / job_id
        branch = f"ocint/{job_id}"
        if not mirror.exists():
            await self._git(self.mirror_root, "clone", "--mirror", repository.remote_url, str(mirror))
            revision_ref = f"refs/heads/{repository.default_branch}"
        else:
            await self._git(mirror, "remote", "set-url", "origin", repository.remote_url)
            revision_ref = f"refs/remotes/origin/{repository.default_branch}"
            await self._git(mirror, "fetch", "origin", f"+refs/heads/{repository.default_branch}:{revision_ref}")
        await self._git(mirror, "config", "remote.origin.mirror", "false")
        revision = (await self._git(mirror, "rev-parse", revision_ref)).strip()
        if not worktree.exists():
            await self._git(mirror, "worktree", "add", str(worktree), "-b", branch, revision)
        return Worktree(path=worktree, branch=branch, base_revision=revision)

    async def validate(self, worktree: Worktree, checks: list[list[str]]) -> None:
        for command in checks:
            if not command:
                raise ValueError("validation commands cannot be empty")
            await self._run(command, worktree.path, self.validation_environment)
        status = (await self._git(worktree.path, "status", "--porcelain")).strip()
        if not status and (await self._git(worktree.path, "rev-parse", "HEAD")).strip() == worktree.base_revision:
            raise ValueError("OpenCode produced no changes")

    async def commit(self, worktree: Worktree, message: str, author_name: str, author_email: str) -> str:
        status = (await self._git(worktree.path, "status", "--porcelain")).strip()
        if not status:
            return (await self._git(worktree.path, "rev-parse", "HEAD")).strip()
        await self._git(worktree.path, "add", "--all")
        await self._git(
            worktree.path,
            "-c",
            f"user.name={author_name}",
            "-c",
            f"user.email={author_email}",
            "commit",
            "--no-verify",
            "-m",
            message,
        )
        return (await self._git(worktree.path, "rev-parse", "HEAD")).strip()

    async def push(self, worktree: Worktree) -> None:
        await self._git(worktree.path, "push", "--no-verify", "--set-upstream", "origin", worktree.branch)

    async def _git(self, cwd: Path, *arguments: str) -> str:
        return await self._run(["git", *arguments], cwd, self.git_environment)

    async def _run(self, arguments: list[str], cwd: Path, environment: Mapping[str, str]) -> str:
        process = await asyncio.create_subprocess_exec(
            *arguments,
            cwd=cwd,
            env=dict(environment),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), self.timeout_seconds)
        except TimeoutError:
            os.killpg(process.pid, 15)
            await process.wait()
            raise RuntimeError(f"managed command timed out: {arguments[0]}") from None
        rendered = output[: self.output_bytes].decode(errors="replace")
        if process.returncode:
            raise RuntimeError(f"managed command failed ({process.returncode}): {rendered}")
        return rendered
