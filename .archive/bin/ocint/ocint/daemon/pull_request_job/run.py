from __future__ import annotations

import asyncio

from ocint.daemon.logging import get_logger
from ocint.daemon.models import (
    PublicationRequest,
    PublishedPublication,
    RefusedPublication,
    ThreadOrigin,
    Worktree,
)
from ocint.daemon.pull_request_job.config import PullRequestJobConfig
from ocint.daemon.pull_request_job.contracts import (
    GitGateway,
    OpenCodeGateway,
    PullRequestJobStore,
    PullRequestPublisher,
)
from ocint.daemon.pull_request_job.models import (
    CommitCheckpoint,
    PromptIntentCheckpoint,
    PromptSubmittedCheckpoint,
    PublicationRefusalCheckpoint,
    PullRequestCheckpoint,
    PullRequestJob,
    PullRequestJobRequest,
    PullRequestJobStage,
    PullRequestJobState,
    PushCheckpoint,
    SessionCheckpoint,
    SourcePullRequestJobRequest,
    StageCheckpoint,
    WorktreeCheckpoint,
)
from ocint.daemon.pull_request_job.service import PromptDecision, authorize, prompt_action

logger = get_logger("service")


class PullRequestJobRunner:
    def __init__(
        self,
        config: PullRequestJobConfig,
        store: PullRequestJobStore,
        opencode: OpenCodeGateway,
        git: GitGateway,
        publisher: PullRequestPublisher,
    ) -> None:
        self.config = config
        self.store = store
        self.opencode = opencode
        self.git = git
        self.publisher = publisher
        self.capacity = asyncio.Semaphore(config.scheduler.capacity)
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.completed = asyncio.Event()
        self.closing = False
        self.activity_generation = 0

    async def start(self) -> None:
        self.schedule_pending(self.recover())

    def recover(self) -> list[str]:
        reconciled = self.store.reconcile()
        pending = self.store.pending_ids()
        logger.info("job recovery completed", reconciled=reconciled, pending=len(pending))
        return pending

    def schedule_pending(self, job_ids: list[str]) -> None:
        for job_id in job_ids:
            if self.store.get(job_id).state is PullRequestJobState.QUEUED:
                self.schedule(job_id)

    def submit(self, request: PullRequestJobRequest) -> PullRequestJob:
        job = self.accept(request)
        if job.state is PullRequestJobState.QUEUED:
            self.schedule(job.id)
        return job

    def accept(self, request: PullRequestJobRequest) -> PullRequestJob:
        authorize(request, self.config)
        job = self.store.submit(request)
        self.activity_generation += 1
        logger.info("job accepted", job=job.id, repository=job.repository, actor=job.actor)
        return job

    def submit_source(self, request: SourcePullRequestJobRequest) -> PullRequestJob:
        job = self.accept_source(request)
        if job.state is PullRequestJobState.QUEUED:
            self.schedule(job.id)
        return job

    def accept_source(self, request: SourcePullRequestJobRequest) -> PullRequestJob:
        job = self.store.submit(request.work)
        self.activity_generation += 1
        logger.info("source job accepted", job=job.id, repository=job.repository, actor=job.actor)
        return job

    def schedule_accepted(self, job_id: str) -> None:
        if self.store.get(job_id).state is PullRequestJobState.QUEUED:
            self.schedule(job_id)

    def retry(self, previous: PullRequestJob, request: PullRequestJobRequest) -> PullRequestJob:
        job = self.accept_retry(previous, request)
        if job.state is PullRequestJobState.QUEUED:
            self.schedule(job.id)
        logger.info("job retry scheduled", previous_job=previous.id, job=job.id, repository=job.repository)
        return job

    def accept_retry(self, previous: PullRequestJob, request: PullRequestJobRequest) -> PullRequestJob:
        authorize(request, self.config)
        job = self.store.retry(previous, request)
        self.activity_generation += 1
        return job

    def retry_source(self, previous: PullRequestJob, request: SourcePullRequestJobRequest) -> PullRequestJob:
        job = self.accept_source_retry(previous, request)
        if job.state is PullRequestJobState.QUEUED:
            self.schedule(job.id)
        logger.info("source job retry scheduled", previous_job=previous.id, job=job.id, repository=job.repository)
        return job

    def accept_source_retry(self, previous: PullRequestJob, request: SourcePullRequestJobRequest) -> PullRequestJob:
        job = self.store.retry(previous, request.work)
        self.activity_generation += 1
        return job

    def get(self, job_id: str) -> PullRequestJob:
        return self.store.get(job_id)

    def reusable(self, candidate_ids: tuple[str, ...]) -> PullRequestJob | None:
        candidates = (self.store.get(job_id) for job_id in candidate_ids)
        return next((job for job in candidates if job.state is PullRequestJobState.COMPLETED), None)

    def abandon(self, job_id: str, reason: str) -> None:
        self.store.fail(job_id, reason)
        task = self.tasks.get(job_id)
        if task is not None:
            task.cancel()
        logger.info("job abandoned", job=job_id, reason=reason)

    @property
    def is_idle(self) -> bool:
        return not self.tasks

    async def wait_until_idle(self) -> None:
        while self.tasks:
            await asyncio.gather(*list(self.tasks.values()))

    async def wait_for_completion(self) -> None:
        if not self.tasks:
            return
        await self.completed.wait()
        self.completed.clear()

    def schedule(self, job_id: str) -> None:
        if self.closing or job_id in self.tasks:
            return
        task = asyncio.create_task(self._run(job_id))
        self.tasks[job_id] = task
        logger.info("job scheduled", job=job_id)

        def completed(_task: asyncio.Task[None], identifier: str = job_id) -> None:
            self.tasks.pop(identifier, None)
            self.completed.set()

        task.add_done_callback(completed)

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
                    logger.info("job claim skipped", job=job_id)
                    return
                logger.info("job started", job=job_id)
                async with asyncio.timeout(self.config.scheduler.job_timeout_seconds):
                    await self._execute(job_id)
        except asyncio.CancelledError:
            self.store.requeue(job_id)
            logger.warning("job cancelled", job=job_id)
            raise
        except TimeoutError:
            self.store.fail(job_id, "job timed out")
            logger.error("job timed out", job=job_id)
        except Exception as error:
            self.store.fail(job_id, str(error)[:2000])
            logger.exception("job failed", job=job_id, error_type=type(error).__name__)

    async def _execute(self, job_id: str) -> None:
        job = self.store.get(job_id)
        repository = self.config.repository(job.repository)
        if job.worktree_path is None:
            logger.info("job stage started", job=job.id, stage="worktree")
            worktree = await self.git.provision(repository.git_repository, job.id)
            job = self.store.checkpoint(
                job.id,
                WorktreeCheckpoint(
                    path=worktree.path,
                    branch=worktree.branch,
                    base_revision=worktree.base_revision,
                ),
            )
            logger.info("job stage completed", job=job.id, stage="worktree", branch=worktree.branch)
        else:
            worktree = Worktree(path=job.worktree_path, branch=job.branch, base_revision=job.base_revision)
        if job.stage is PullRequestJobStage.EXECUTION:
            logger.info("job stage started", job=job.id, stage=PullRequestJobStage.EXECUTION.value)
            if not job.session_id:
                session_id = await self.opencode.create(worktree.path, f"ocint:{job.id}")
                job = self.store.checkpoint(
                    job.id, SessionCheckpoint(session_id=session_id, server_url=self.opencode.server_url)
                )
            observation = await self.opencode.observe_prompt(worktree.path, job.session_id, job.prompt)
            action = prompt_action(observation)
            if action is PromptDecision.SUBMIT:
                job = self.store.checkpoint(job.id, PromptIntentCheckpoint())
                await self.opencode.prompt(worktree.path, job.session_id, job.prompt)
                job = self.store.checkpoint(job.id, PromptSubmittedCheckpoint())
            if action is not PromptDecision.ADVANCE:
                await self.opencode.wait_for_completion(worktree.path, job.session_id, job.prompt)
            job = self.store.checkpoint(job.id, StageCheckpoint(stage=PullRequestJobStage.VALIDATION))
            logger.info("job stage completed", job=job.id, stage=PullRequestJobStage.EXECUTION.value)
        if job.stage is PullRequestJobStage.VALIDATION:
            logger.info("job stage started", job=job.id, stage=PullRequestJobStage.VALIDATION.value)
            await self.git.validate(worktree, repository.checks)
            job = self.store.checkpoint(job.id, StageCheckpoint(stage=PullRequestJobStage.COMMIT))
            logger.info("job stage completed", job=job.id, stage=PullRequestJobStage.VALIDATION.value)
        if job.stage is PullRequestJobStage.COMMIT:
            logger.info("job stage started", job=job.id, stage=PullRequestJobStage.COMMIT.value)
            commit = await self.git.commit(worktree, job.title, repository.author_name, repository.author_email)
            job = self.store.checkpoint(job.id, CommitCheckpoint(sha=commit))
            logger.info("job stage completed", job=job.id, stage=PullRequestJobStage.COMMIT.value, commit=commit)
        if job.stage is PullRequestJobStage.PUSH:
            logger.info("job stage started", job=job.id, stage=PullRequestJobStage.PUSH.value)
            await self.git.push(worktree)
            job = self.store.checkpoint(job.id, PushCheckpoint(revision=job.commit_sha))
            logger.info("job stage completed", job=job.id, stage=PullRequestJobStage.PUSH.value, branch=worktree.branch)
        if job.stage is PullRequestJobStage.PULL_REQUEST:
            logger.info("job stage started", job=job.id, stage=PullRequestJobStage.PULL_REQUEST.value)
            ownership = (
                self.store.owned_pull_request(job.origin.source_thread_id, repository.github_repository)
                if isinstance(job.origin, ThreadOrigin)
                else None
            )
            result = await self.publisher.publish(
                PublicationRequest(
                    repository=repository.github_repository,
                    branch=worktree.branch,
                    base=repository.git_repository.default_branch,
                    title=job.title,
                    body="Automated by ocint daemon.",
                    origin=job.origin,
                    owned_pull_request_number=ownership[0] if ownership else 0,
                )
            )
            if isinstance(result, RefusedPublication):
                self.store.checkpoint(job.id, PublicationRefusalCheckpoint(reason=result.reason))
                raise RuntimeError("owned pull request is closed or merged")
            if not isinstance(result, PublishedPublication):
                raise RuntimeError("unsupported publication result")
            if isinstance(job.origin, ThreadOrigin):
                self.store.set_owned_pull_request(
                    job.origin.source_thread_id, repository.github_repository, result.number, result.url
                )
            self.store.checkpoint(job.id, PullRequestCheckpoint(url=result.url))
            logger.info(
                "job stage completed", job=job.id, stage=PullRequestJobStage.PULL_REQUEST.value, pull_request=result.url
            )
        self.store.complete(job.id)
        logger.info("job completed", job=job.id, repository=job.repository)
