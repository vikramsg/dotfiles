"""Provider-neutral thread task workflow."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ocint.daemon.tasks.models import MessageClassification, Task, TaskKind, TaskState, Thread, ThreadMessage
from ocint.daemon.tasks.run import PullRequestJobs, TaskCoordinator, ThreadSource


@contextmanager
def open_task_coordinator(
    database_path: Path,
    source: ThreadSource,
    jobs: PullRequestJobs,
) -> Iterator[TaskCoordinator]:
    from ocint.daemon.db import create_daemon_engine
    from ocint.daemon.tasks.repository import TaskRepository

    engine = create_daemon_engine(database_path)
    try:
        yield TaskCoordinator(source, TaskRepository(engine), jobs)
    finally:
        engine.dispose()


__all__ = [
    "MessageClassification",
    "Task",
    "TaskCoordinator",
    "TaskKind",
    "TaskState",
    "Thread",
    "ThreadMessage",
    "open_task_coordinator",
]
