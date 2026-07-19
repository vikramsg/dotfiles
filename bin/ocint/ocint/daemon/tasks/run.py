from typing import Protocol

from ocint.daemon.logging import get_logger
from ocint.daemon.service import Job, JobState, WorkRequest
from ocint.daemon.tasks.models import Task, TaskKind, TaskState
from ocint.daemon.tasks.repository import TaskRepository
from ocint.daemon.tasks.service import render_prompt

logger = get_logger("tasks")


class ThreadSource(Protocol):
    async def poll(self) -> None: ...
    async def complete_task(self, task: Task, job: Job) -> None: ...


class TaskExecutor(Protocol):
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
            if not thread.eligible:
                self._skip_ineligible(current)
                continue
            if current is not None:
                current = await self._reconcile_current(thread.id, current)
            if current is None:
                pending = self.repository.unassigned_messages(thread.id)
                latest = self.repository.latest(thread.id)
                if latest is None:
                    current = self.repository.create(thread.id, TaskKind.INITIAL, pending, 0)
                    logger.info("task created", task=current.id, thread=thread.id, kind=current.kind.value)
                elif pending:
                    current = self.repository.create(thread.id, TaskKind.FOLLOW_UP, pending, latest.id)
                    job_id = self.repository.execution_job_id(thread.id)
                    previous = self.executor.get(job_id) if job_id else None
                    logger.info("task created", task=current.id, thread=thread.id, kind=current.kind.value)
            if current is not None and not self.repository.latest_job_id(current.id):
                self._start(thread.id, current, previous)
        return any(self.repository.unresolved(thread.id) is not None for thread in self.repository.threads())

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

    async def _reconcile_current(self, thread_id: int, current: Task) -> Task | None:
        job_id = self.repository.latest_job_id(current.id)
        if not job_id:
            return current
        job = self.executor.get(job_id)
        if job.state in {JobState.QUEUED, JobState.RUNNING}:
            return current
        if job.state is JobState.COMPLETED:
            await self.source.complete_task(current, job)
            self.repository.set_execution_job(thread_id, job.id)
            return None
        pending = self.repository.unassigned_messages(thread_id)
        if pending:
            successor = self.repository.create(thread_id, TaskKind.FOLLOW_UP, pending, current.id)
            reason = f"superseded by task {successor.id} after new thread messages"
            self.repository.set_state(current.id, TaskState.SKIPPED, reason)
            logger.info("task skipped", task=current.id, successor=successor.id, reason=reason)
            self._start(thread_id, successor, job)
            return successor
        self._start(thread_id, current, job)
        return current

    def _start(self, thread_id: int, task: Task, previous: Job | None) -> None:
        thread = next(item for item in self.repository.threads() if item.id == thread_id)
        prompt = render_prompt(thread, self.repository.accepted_messages(thread_id))
        attempt = self.repository.attempt_count(task.id) + 1
        request = WorkRequest(
            idempotency_key=f"thread-task:{task.id}:attempt:{attempt}",
            actor=thread.actor,
            repository=thread.repository,
            prompt=prompt,
        )
        job = self.executor.submit(request) if previous is None else self.executor.retry(previous, request)
        self.repository.attach_job(task.id, job.id)
        logger.info("task job scheduled", task=task.id, thread=thread.id, job=job.id)
