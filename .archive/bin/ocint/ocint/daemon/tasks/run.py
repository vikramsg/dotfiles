from __future__ import annotations

from typing import Protocol

from ocint.daemon.logging import get_logger
from ocint.daemon.models import (
    MessageClassification,
    ObservedMessage,
    ReplyOutcome,
    ReplyRequest,
    ThreadObservations,
    ThreadOrigin,
)
from ocint.daemon.pull_request_job import (
    PullRequestJob,
    PullRequestJobRequest,
    PullRequestJobState,
    SourcePullRequestJobRequest,
)
from ocint.daemon.tasks.models import (
    FailedTaskRetry,
    RetryAttachment,
    SuccessorCreated,
    SuccessorExisting,
    Task,
    TaskKind,
    TaskReason,
    TaskState,
    Thread,
)
from ocint.daemon.tasks.repository import TaskRepository
from ocint.daemon.tasks.service import render_prompt

logger = get_logger("tasks")


class ThreadSource(Protocol):
    async def observe(self) -> ThreadObservations: ...
    async def reply(self, request: ReplyRequest) -> ObservedMessage: ...


class RoutedThreadSource(ThreadSource, Protocol):
    @property
    def source_prefix(self) -> str: ...


class SourceRouter:
    """Combine source observation while routing replies by globally-prefixed IDs."""

    def __init__(self, sources: tuple[RoutedThreadSource, ...]) -> None:
        self.sources = sources

    async def observe(self) -> ThreadObservations:
        observations = []
        for source in self.sources:
            observations.extend((await source.observe()).root)
        return ThreadObservations(root=observations)

    async def reply(self, request: ReplyRequest) -> ObservedMessage:
        source = next((item for item in self.sources if request.source_thread_id.startswith(item.source_prefix)), None)
        if source is None:
            raise ValueError(f"no source route for {request.source_thread_id}")
        return await source.reply(request)


class PullRequestJobs(Protocol):
    def accept(self, request: PullRequestJobRequest) -> PullRequestJob: ...
    def accept_source_retry(self, previous: PullRequestJob, request: SourcePullRequestJobRequest) -> PullRequestJob: ...
    def schedule_accepted(self, job_id: str) -> None: ...
    def submit_source(self, request: SourcePullRequestJobRequest) -> PullRequestJob: ...
    def retry_source(self, previous: PullRequestJob, request: SourcePullRequestJobRequest) -> PullRequestJob: ...
    def get(self, job_id: str) -> PullRequestJob: ...
    def reusable(self, candidate_ids: tuple[str, ...]) -> PullRequestJob | None: ...
    def abandon(self, job_id: str, reason: str) -> None: ...


class TaskCoordinator:
    def __init__(self, source: ThreadSource, repository: TaskRepository, executor: PullRequestJobs) -> None:
        self.source = source
        self.repository = repository
        self.executor = executor

    async def reconcile(self) -> bool:
        await self._ingest_observations()
        for thread in self.repository.threads():
            current = self.repository.unresolved(thread.id)
            previous: PullRequestJob | None = None
            if not thread.eligible:
                self._skip_ineligible(current)
                continue
            if current is not None:
                current = await self._reconcile_current(current)
            if current is None:
                latest = self.repository.latest(thread.id)
                kind = TaskKind.INITIAL if latest is None else TaskKind.FOLLOW_UP
                predecessor = 0 if latest is None else latest.id
                current = self.repository.create_pending(thread.id, kind, predecessor)
                if current is not None:
                    previous = self.executor.reusable(self.repository.reusable_job_ids(thread.id))
                    logger.info("task created", task=current.id, thread=thread.id, kind=current.kind.value)
            if current is not None and not self.repository.latest_job_id(current.id):
                self._start(thread, current, previous)
        return any(
            thread.eligible and self.repository.unresolved(thread.id) is not None
            for thread in self.repository.threads()
        )

    def _skip_ineligible(self, current: Task | None) -> None:
        if current is None:
            return
        job_id = self.repository.latest_job_id(current.id)
        if job_id:
            job = self.executor.get(job_id)
            if job.state is PullRequestJobState.RUNNING:
                return
            if job.state is PullRequestJobState.QUEUED:
                self.executor.abandon(job.id, "source thread is no longer eligible")
        reason = "source thread is no longer eligible"
        self.repository.set_state(current.id, TaskState.SKIPPED, reason)
        logger.info("task skipped", task=current.id, reason=reason)

    async def _reconcile_current(self, current: Task) -> Task | None:
        job_id = self.repository.latest_job_id(current.id)
        if not job_id:
            return current
        job = self.executor.get(job_id)
        if job.state in {PullRequestJobState.QUEUED, PullRequestJobState.RUNNING}:
            return current
        if job.state is PullRequestJobState.COMPLETED:
            await self._complete(current, job)
            return None
        if job.publication_refusal:
            await self._refuse_publication(current)
            return None
        reason = "superseded after new thread messages"
        claim = self.repository.claim_failed(current, reason)
        if isinstance(claim, SuccessorCreated):
            logger.info("task skipped", task=current.id, successor=claim.task.id, reason=reason)
            self._start(self.repository.thread(current.thread_id), claim.task, job)
            return claim.task
        if isinstance(claim, SuccessorExisting):
            return None
        if isinstance(claim, FailedTaskRetry):
            self._retry_claimed(self.repository.thread(current.thread_id), claim, job)
            return claim.task
        return None

    def _start(self, thread: Thread, task: Task, previous: PullRequestJob | None) -> None:
        attempt = self.repository.attempt_count(task.id) + 1
        request = self._request(thread, task, attempt)
        source_request = SourcePullRequestJobRequest(work=request)
        job = (
            self.executor.submit_source(source_request)
            if previous is None
            else self.executor.retry_source(previous, source_request)
        )
        self.repository.attach_job(task.id, job.id)
        logger.info("task job scheduled", task=task.id, thread=thread.id, job=job.id)

    def _retry_claimed(self, thread: Thread, claim: FailedTaskRetry, previous: PullRequestJob) -> None:
        request = self._request(thread, claim.task, claim.attempt)
        job = self.executor.accept_source_retry(previous, SourcePullRequestJobRequest(work=request))
        attachment = self.repository.attach_claimed_job(claim.task.id, claim.attempt, job.id)
        if attachment is RetryAttachment.ATTACHED:
            self.executor.schedule_accepted(job.id)
            logger.info("task job scheduled", task=claim.task.id, thread=thread.id, job=job.id)
        elif attachment is RetryAttachment.REJECTED:
            self.executor.abandon(job.id, "task is no longer current")

    def _request(self, thread: Thread, task: Task, attempt: int) -> PullRequestJobRequest:
        if not thread.title:
            raise RuntimeError(f"source thread {thread.id} has no work title")
        messages = self.repository.actionable_messages(thread.id)
        task_messages = self.repository.task_messages(task.id)
        actor = task_messages[-1].actor
        return PullRequestJobRequest(
            idempotency_key=(f"thread-task:model-v2:source:{thread.source_id}:task:{task.id}:attempt:{attempt}"),
            actor=actor,
            repository=thread.configured_repository,
            title=thread.title,
            prompt=render_prompt(thread, messages),
            origin=ThreadOrigin(source_thread_id=thread.source_id, source_anchor_id=task_messages[-1].source_id),
        )

    async def _ingest_observations(self) -> None:
        observations = await self.source.observe()
        for observation in observations.root:
            thread = self.repository.upsert_thread(
                observation.source_id,
                observation.title,
                observation.configured_repository,
                observation.eligible,
            )
            for observed in observation.messages.root:
                message = self.repository.upsert_message(
                    thread.id,
                    observed.source_id,
                    observed.actor,
                    observed.classification,
                    observed.body,
                    observed.source_created_at,
                )
                if observed.classification is MessageClassification.UNAUTHORIZED:
                    response = await self.source.reply(
                        ReplyRequest(
                            source_thread_id=thread.source_id,
                            source_anchor_id=message.source_id,
                            outcome=ReplyOutcome.UNAUTHORIZED,
                            text=f"Actor @{observed.actor} is not authorized.",
                        )
                    )
                    self.repository.upsert_message(
                        thread.id,
                        response.source_id,
                        response.actor,
                        response.classification,
                        response.body,
                        response.source_created_at,
                    )

    async def _complete(self, task: Task, job: PullRequestJob) -> None:
        if not isinstance(job.origin, ThreadOrigin):
            raise RuntimeError(f"task {task.id} completed with a direct-origin job")
        if not job.pull_request_url:
            raise RuntimeError(f"task {task.id} completed without a pull request URL")
        response = await self.source.reply(
            ReplyRequest(
                source_thread_id=job.origin.source_thread_id,
                source_anchor_id=job.origin.source_anchor_id,
                outcome=ReplyOutcome.ADDRESSED,
                text=f"Issue addressed: {job.pull_request_url}\n\nTo make further changes, add a comment.",
            )
        )
        self._ingest_reply(task.thread_id, response)
        self.repository.set_state(task.id, TaskState.ADDRESSED)
        logger.info("task addressed", task=task.id, thread=task.thread_id, pull_request=job.pull_request_url)

    async def _refuse_publication(self, task: Task) -> None:
        messages = self.repository.task_messages(task.id)
        if not messages:
            raise RuntimeError(f"task {task.id} has no messages")
        thread = self.repository.thread(task.thread_id)
        response = await self.source.reply(
            ReplyRequest(
                source_thread_id=thread.source_id,
                source_anchor_id=messages[-1].source_id,
                outcome=ReplyOutcome.CLOSED_PULL_REQUEST,
                text="The owned pull request is closed or merged; no replacement will be created.",
            )
        )
        self._ingest_reply(task.thread_id, response)
        self.repository.set_state(task.id, TaskState.ERRORED, TaskReason.OWNED_PULL_REQUEST_CLOSED.value)

    def _ingest_reply(self, thread_id: int, response: ObservedMessage) -> None:
        self.repository.upsert_message(
            thread_id,
            response.source_id,
            response.actor,
            response.classification,
            response.body,
            response.source_created_at,
        )
