import fcntl
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

import aiohttp
from pydantic import BaseModel, ConfigDict, TypeAdapter

from ocint.daemon.config import RepositoryConfig
from ocint.daemon.models import Artifact, Worktree


class GitHubPull(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    html_url: str
    number: int


class ManagedCommand:
    def __init__(
        self,
        timeout_seconds: int,
        output_bytes: int,
        secrets: frozenset[str],
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.output_bytes = output_bytes
        self.secrets = frozenset(secret for secret in secrets if secret)

    def run(
        self,
        arguments: list[str],
        cwd: Path,
        environment: Mapping[str, str],
        cancelled: threading.Event,
    ) -> str:
        if not arguments or any("\x00" in argument for argument in arguments):
            raise ValueError("invalid managed command arguments")
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen(
                arguments,
                cwd=cwd,
                env=dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            deadline = time.monotonic() + self.timeout_seconds
            while process.poll() is None:
                if cancelled.is_set() or time.monotonic() >= deadline:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    reason = "cancelled" if cancelled.is_set() else "timed out"
                    raise RuntimeError(f"managed command {reason}: {arguments[0]}")
                time.sleep(0.05)
            output.seek(0)
            rendered = output.read(self.output_bytes + 1).decode(errors="replace")
        if len(rendered.encode()) > self.output_bytes:
            rendered = rendered[: self.output_bytes] + "\n[output truncated]"
        for secret in self.secrets:
            rendered = rendered.replace(secret, "[REDACTED]")
        if process.returncode:
            raise RuntimeError(f"managed command failed ({process.returncode}): {rendered}")
        return rendered


class RepositoryManager:
    def __init__(
        self,
        mirror_root: Path,
        worktree_root: Path,
        command: ManagedCommand,
        validation_environment: Mapping[str, str],
        git_environment: Mapping[str, str],
    ) -> None:
        self.mirror_root = mirror_root.resolve()
        self.worktree_root = worktree_root.resolve()
        self.command = command
        self.validation_environment = validation_environment
        self.git_environment = git_environment

    def provision(self, repository: RepositoryConfig, job_id: str, cancelled: threading.Event) -> Worktree:
        self.mirror_root.mkdir(parents=True, exist_ok=True)
        self.worktree_root.mkdir(parents=True, exist_ok=True)
        safe_name = self._safe(repository.name)
        mirror = self._contained(self.mirror_root, self.mirror_root / f"{safe_name}.git")
        worktree = self._contained(self.worktree_root, self.worktree_root / job_id)
        branch = f"ocint/{job_id}"
        with self._lock(self.mirror_root / f".{safe_name}.lock"):
            if not mirror.exists():
                self._git(self.mirror_root, cancelled, "clone", "--mirror", repository.remote_url, str(mirror))
                revision_ref = f"refs/heads/{repository.default_branch}"
            else:
                self._git(mirror, cancelled, "remote", "set-url", "origin", repository.remote_url)
                self._git(mirror, cancelled, "config", "remote.origin.mirror", "false")
                revision_ref = f"refs/remotes/origin/{repository.default_branch}"
                self._git(
                    mirror,
                    cancelled,
                    "fetch",
                    "origin",
                    f"+refs/heads/{repository.default_branch}:{revision_ref}",
                )
            self._git(mirror, cancelled, "config", "remote.origin.mirror", "false")
            revision = self._git(mirror, cancelled, "rev-parse", revision_ref).strip()
            if not (worktree / ".git").exists():
                branch_exists = self._branch_exists(mirror, branch, cancelled)
                arguments = ["worktree", "add", str(worktree)]
                if branch_exists:
                    arguments.append(branch)
                else:
                    arguments.extend(["-b", branch, revision])
                self._git(mirror, cancelled, *arguments)
        return Worktree(path=worktree, branch=branch, base_revision=revision)

    def validate(self, worktree: Worktree, checks: list[list[str]], cancelled: threading.Event) -> None:
        for arguments in checks:
            if not arguments:
                raise ValueError("validation commands cannot be empty")
            self.command.run(arguments, worktree.path, self.validation_environment, cancelled)
        if not self._git(worktree.path, cancelled, "status", "--porcelain").strip():
            head = self._git(worktree.path, cancelled, "rev-parse", "HEAD").strip()
            if head == worktree.base_revision:
                raise ValueError("OpenCode produced no changes")

    def has_changes(self, worktree: Worktree, cancelled: threading.Event) -> bool:
        return bool(self._git(worktree.path, cancelled, "status", "--porcelain").strip())

    def commit(self, worktree: Worktree, message: str, cancelled: threading.Event) -> str:
        head = self._git(worktree.path, cancelled, "rev-parse", "HEAD").strip()
        if head != worktree.base_revision and not self._git(worktree.path, cancelled, "status", "--porcelain").strip():
            return head
        self._git(worktree.path, cancelled, "add", "--all")
        self._git(worktree.path, cancelled, "commit", "--no-verify", "-m", message)
        return self._git(worktree.path, cancelled, "rev-parse", "HEAD").strip()

    def push(self, worktree: Worktree, cancelled: threading.Event) -> None:
        with self._lock(self.mirror_root / ".publish.lock"):
            self._git(
                worktree.path,
                cancelled,
                "push",
                "--no-verify",
                "--set-upstream",
                "origin",
                worktree.branch,
            )

    def retire(self, repository: RepositoryConfig, worktree: Worktree, cancelled: threading.Event) -> None:
        mirror = self._contained(self.mirror_root, self.mirror_root / f"{self._safe(repository.name)}.git")
        with self._lock(self.mirror_root / f".{self._safe(repository.name)}.lock"):
            if not worktree.path.exists():
                self._git(mirror, cancelled, "worktree", "prune")
                return
            registered = self._git(mirror, cancelled, "worktree", "list", "--porcelain")
            if f"worktree {worktree.path}\n" not in registered:
                contained = self._contained(self.worktree_root, worktree.path)
                database_files = [*contained.rglob("*.db"), *contained.rglob("*.sqlite")]
                if database_files:
                    raise RuntimeError("refusing to retire a detached worktree containing database files")
                shutil.rmtree(contained)
                return
            self._git(
                mirror,
                cancelled,
                "worktree",
                "remove",
                "--force",
                str(self._contained(self.worktree_root, worktree.path)),
            )

    def _branch_exists(self, mirror: Path, branch: str, cancelled: threading.Event) -> bool:
        try:
            self._git(mirror, cancelled, "show-ref", "--verify", f"refs/heads/{branch}")
        except RuntimeError:
            return False
        return True

    def _safe(self, name: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
            raise ValueError(f"unsafe repository name: {name}")
        return name

    def _contained(self, root: Path, candidate: Path) -> Path:
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(f"path escapes managed root: {candidate}")
        return resolved

    @contextmanager
    def _lock(self, path: Path) -> Iterator[None]:
        with path.open("a+") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _git(self, cwd: Path, cancelled: threading.Event, *arguments: str) -> str:
        return self.command.run(["git", *arguments], cwd, self.git_environment, cancelled)


class GitHubPublisher:
    def __init__(self, api_url: str, token: str) -> None:
        self.api_url = api_url.rstrip("/")
        self.token = token

    async def publish(self, repository: str, branch: str, base: str, title: str, body: str) -> Artifact:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        owner = repository.split("/", maxsplit=1)[0]
        params = {"state": "open", "head": f"{owner}:{branch}", "base": base}
        async with aiohttp.ClientSession(headers=headers) as client:
            async with client.get(f"{self.api_url}/repos/{repository}/pulls", params=params) as response:
                response.raise_for_status()
                pulls = TypeAdapter(list[GitHubPull]).validate_python(await response.json())
            pull = pulls[0] if pulls else await self._create(client, repository, branch, base, title, body)
        return Artifact(kind="pull_request", value=str(pull.number), url=pull.html_url)

    async def _create(
        self,
        client: aiohttp.ClientSession,
        repository: str,
        branch: str,
        base: str,
        title: str,
        body: str,
    ) -> GitHubPull:
        async with client.post(
            f"{self.api_url}/repos/{repository}/pulls",
            json={"head": branch, "base": base, "title": title, "body": body},
        ) as response:
            response.raise_for_status()
            return GitHubPull.model_validate(await response.json())
