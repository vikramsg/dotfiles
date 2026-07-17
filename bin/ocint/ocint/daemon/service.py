from __future__ import annotations

import asyncio
from enum import StrEnum
from pathlib import Path
from shlex import join
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from ocint.daemon.config import DaemonConfig, RepositoryConfig


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStage(StrEnum):
    EXECUTION = "execution"
    VALIDATION = "validation"
    COMMIT = "commit"
    PUSH = "push"
    PULL_REQUEST = "pull_request"
    COMPLETE = "complete"


class WorkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    idempotency_key: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    prompt: str = Field(min_length=1)


class Job(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    idempotency_key: str
    actor: str
    repository: str
    prompt: str
    state: JobState
    stage: JobStage
    session_id: str
    server_url: str
    worktree_path: Path | None
    branch: str
    base_revision: str
    prompt_intended: bool
    prompt_submitted: bool
    commit_sha: str
    pushed: bool
    pull_request_url: str
    error: str
    created_at: str
    updated_at: str


class Worktree(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: Path
    branch: str
    base_revision: str


class PromptObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    found: bool
    completed: bool


class JobStore(Protocol):
    def submit(self, request: WorkRequest) -> Job: ...
    def claim(self, job_id: str) -> Job | None: ...
    def pending_ids(self) -> list[str]: ...
    def get(self, job_id: str) -> Job: ...
    def checkpoint(self, job_id: str, stage: JobStage, **values: str | bool) -> Job: ...
    def finish(self, job_id: str, state: JobState, error: str = "") -> Job: ...
    def requeue(self, job_id: str) -> None: ...
    def reconcile(self) -> int: ...


class OpenCode(Protocol):
    server_url: str

    async def create(self, directory: Path, identity: str) -> str: ...
    async def observe_prompt(self, directory: Path, session_id: str, text: str) -> PromptObservation: ...
    async def prompt(self, directory: Path, session_id: str, text: str) -> None: ...
    async def wait_idle(self, directory: Path, session_id: str) -> None: ...


class Git(Protocol):
    async def provision(self, repository: RepositoryConfig, job_id: str) -> Worktree: ...
    async def validate(self, worktree: Worktree, checks: list[list[str]]) -> None: ...
    async def commit(self, worktree: Worktree, message: str, author_name: str, author_email: str) -> str: ...
    async def push(self, worktree: Worktree) -> None: ...


class GitHub(Protocol):
    async def publish(self, repository: str, branch: str, base: str, title: str, body: str) -> str: ...


def authorize(request: WorkRequest, config: DaemonConfig) -> None:
    repository = config.repository(request.repository)
    if repository.actors and request.actor not in repository.actors:
        raise PermissionError(f"actor is not allowed for {request.repository}: {request.actor}")


def attach_command(job: Job) -> str:
    if not job.session_id or job.worktree_path is None or not job.server_url:
        return ""
    return join(["opencode", "attach", job.server_url, "--dir", str(job.worktree_path), "--session", job.session_id])


def prompt_action(observation: PromptObservation) -> str:
    if observation.completed:
        return "advance"
    if observation.found:
        return "wait"
    return "submit"


class JobExecutor:
    def __init__(self, config: DaemonConfig, store: JobStore, opencode: OpenCode, git: Git, github: GitHub) -> None:
        self.config = config
        self.store = store
        self.opencode = opencode
        self.git = git
        self.github = github
        self.capacity = asyncio.Semaphore(config.scheduler.capacity)
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.closing = False

    async def start(self) -> None:
        self.store.reconcile()
        for job_id in self.store.pending_ids():
            self.schedule(job_id)

    def submit(self, request: WorkRequest) -> Job:
        authorize(request, self.config)
        job = self.store.submit(request)
        self.schedule(job.id)
        return job

    def schedule(self, job_id: str) -> None:
        if self.closing or job_id in self.tasks:
            return
        task = asyncio.create_task(self._run(job_id))
        self.tasks[job_id] = task
        task.add_done_callback(lambda _task, identifier=job_id: self.tasks.pop(identifier, None))

    async def close(self) -> None:
        self.closing = True
        if not self.tasks:
            return
        tasks = list(self.tasks.values())
        try:
            async with asyncio.timeout(self.config.scheduler.shutdown_timeout_seconds):
                await asyncio.gather(*tasks)
        except TimeoutError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self, job_id: str) -> None:
        try:
            async with self.capacity:
                if self.store.claim(job_id) is None:
                    return
                async with asyncio.timeout(self.config.scheduler.job_timeout_seconds):
                    await self.execute(job_id)
        except asyncio.CancelledError:
            self.store.requeue(job_id)
            raise
        except TimeoutError:
            self.store.finish(job_id, JobState.FAILED, "job timed out")
        except Exception as error:
            self.store.finish(job_id, JobState.FAILED, str(error)[:2000])

    async def execute(self, job_id: str) -> None:
        job = self.store.get(job_id)
        repository = self.config.repository(job.repository)
        if job.worktree_path is None:
            worktree = await self.git.provision(repository, job.id)
            job = self.store.checkpoint(
                job.id,
                job.stage,
                worktree_path=str(worktree.path),
                branch=worktree.branch,
                base_revision=worktree.base_revision,
            )
        else:
            worktree = Worktree(path=job.worktree_path, branch=job.branch, base_revision=job.base_revision)
        if job.stage is JobStage.EXECUTION:
            if not job.session_id:
                session_id = await self.opencode.create(worktree.path, f"ocint:{job.id}")
                job = self.store.checkpoint(
                    job.id, JobStage.EXECUTION, session_id=session_id, server_url=self.opencode.server_url
                )
            observation = await self.opencode.observe_prompt(worktree.path, job.session_id, job.prompt)
            action = prompt_action(observation)
            if action == "submit":
                job = self.store.checkpoint(job.id, JobStage.EXECUTION, prompt_intended=True)
                await self.opencode.prompt(worktree.path, job.session_id, job.prompt)
                job = self.store.checkpoint(job.id, JobStage.EXECUTION, prompt_submitted=True)
            if action != "advance":
                await self.opencode.wait_idle(worktree.path, job.session_id)
            job = self.store.checkpoint(job.id, JobStage.VALIDATION)
        if job.stage is JobStage.VALIDATION:
            await self.git.validate(worktree, repository.checks)
            job = self.store.checkpoint(job.id, JobStage.COMMIT)
        if job.stage is JobStage.COMMIT:
            commit = await self.git.commit(
                worktree, f"ocint: complete job {job.id}", repository.author_name, repository.author_email
            )
            job = self.store.checkpoint(job.id, JobStage.PUSH, commit_sha=commit)
        if job.stage is JobStage.PUSH:
            await self.git.push(worktree)
            job = self.store.checkpoint(job.id, JobStage.PULL_REQUEST, pushed=True)
        if job.stage is JobStage.PULL_REQUEST:
            url = await self.github.publish(
                repository.github_repository,
                worktree.branch,
                repository.default_branch,
                f"ocint: complete job {job.id}",
                "Automated by ocint daemon.",
            )
            self.store.checkpoint(job.id, JobStage.COMPLETE, pull_request_url=url)
        self.store.finish(job.id, JobState.COMPLETED)
