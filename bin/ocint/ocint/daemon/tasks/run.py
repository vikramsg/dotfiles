from __future__ import annotations

from typing import Protocol

from ocint.daemon.logging import get_logger
from ocint.daemon.models import Job, JobState
from ocint.daemon.service import WorkRequest
from ocint.daemon.tasks.models import (
    FailedTaskRetry,
    RetryAttachment,
    SuccessorCreated,
    SuccessorExisting,
    Task,
    TaskKind,
    TaskState,
    Thread,
)
from ocint.daemon.tasks.repository import TaskRepository
from ocint.daemon.tasks.service import render_prompt

logger = get_logger("tasks")


class ThreadSource(Protocol):
    async def poll(self) -> None: ...
    async def complete_task(self, task: Task, job: Job) -> None: ...
    def eligible(self, thread_id: int) -> bool: ...
    def configured_repository(self, thread_id: int) -> str: ...


class TaskExecutor(Protocol):
    def accept(self, request: WorkRequest) -> Job: ...
    def accept_retry(self, previous: Job, request: WorkRequest) -> Job: ...
    def schedule_accepted(self, job_id: str) -> None: ...
    def submit(self, request: WorkRequest) -> Job: ...
    def retry(self, previous: Job, request: WorkRequest) -> Job: ...
    def get(self, job_id: str) -> Job: ...
    def abandon(self, job_id: str, reason: str) -> None: ...


class TaskCoordinator:
    def __init__(self, source: ThreadSource, repository: TaskRepository, executor: TaskExecutor) -> None:
        self.source = source
        self.repository = repository
        self.executor = executor

    async def reconcile(self) -> bool:
        await self.source.poll()
        for thread in self.repository.threads():
            current = self.repository.unresolved(thread.id)
            previous: Job | None = None
            if not self.source.eligible(thread.id):
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
                    reusable_job_id = self.repository.reusable_job_id(thread.id)
                    previous = self.executor.get(reusable_job_id) if reusable_job_id else None
                    logger.info("task created", task=current.id, thread=thread.id, kind=current.kind.value)
            if current is not None and not self.repository.latest_job_id(current.id):
                self._start(thread, current, previous)
        return any(
            self.source.eligible(thread.id) and self.repository.unresolved(thread.id) is not None
            for thread in self.repository.threads()
        )

    def _skip_ineligible(self, current: Task | None) -> None:
        if current is None:
            return
        job_id = self.repository.latest_job_id(current.id)
        if job_id:
            job = self.executor.get(job_id)
            if job.state is JobState.RUNNING:
                return
            if job.state is JobState.QUEUED:
                self.executor.abandon(job.id, "source thread is no longer eligible")
        reason = "source thread is no longer eligible"
        self.repository.set_state(current.id, TaskState.SKIPPED, reason)
        logger.info("task skipped", task=current.id, reason=reason)

    async def _reconcile_current(self, current: Task) -> Task | None:
        job_id = self.repository.latest_job_id(current.id)
        if not job_id:
            return current
        job = self.executor.get(job_id)
        if job.state in {JobState.QUEUED, JobState.RUNNING}:
            return current
        if job.state is JobState.COMPLETED:
            await self.source.complete_task(current, job)
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

    def _start(self, thread: Thread, task: Task, previous: Job | None) -> None:
        attempt = self.repository.attempt_count(task.id) + 1
        request = self._request(thread, task, attempt)
        job = self.executor.submit(request) if previous is None else self.executor.retry(previous, request)
        self.repository.attach_job(task.id, job.id)
        logger.info("task job scheduled", task=task.id, thread=thread.id, job=job.id)

    def _retry_claimed(self, thread: Thread, claim: FailedTaskRetry, previous: Job) -> None:
        request = self._request(thread, claim.task, claim.attempt)
        job = self.executor.accept_retry(previous, request)
        attachment = self.repository.attach_claimed_job(claim.task.id, claim.attempt, job.id)
        if attachment is RetryAttachment.ATTACHED:
            self.executor.schedule_accepted(job.id)
            logger.info("task job scheduled", task=claim.task.id, thread=thread.id, job=job.id)
        elif attachment is RetryAttachment.REJECTED:
            self.executor.abandon(job.id, "task is no longer current")

    def _request(self, thread: Thread, task: Task, attempt: int) -> WorkRequest:
        messages = self.repository.actionable_messages(thread.id)
        task_messages = self.repository.task_messages(task.id)
        actor = task_messages[-1].actor
        return WorkRequest(
            idempotency_key=(f"thread-task:model-v2:source:{thread.source_id}:task:{task.id}:attempt:{attempt}"),
            actor=actor,
            repository=self.source.configured_repository(thread.id),
            prompt=render_prompt(thread, messages),
        )
