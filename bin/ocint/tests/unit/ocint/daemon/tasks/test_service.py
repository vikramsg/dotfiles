from pathlib import Path

from ocint.daemon.db import create_daemon_engine
from ocint.daemon.db.schema import metadata
from ocint.daemon.tasks.models import MessageActorType, MessageDisposition, TaskKind, TaskState
from ocint.daemon.tasks.repository import TaskRepository


def test_task_repository_batches_only_unassigned_accepted_messages(tmp_path: Path) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "control.sqlite")
    metadata.create_all(engine)
    repository = TaskRepository(engine)
    thread = repository.upsert_thread("repo", "github", "5", "alice", "Title", "Body")
    first = repository.upsert_message(
        thread.id,
        "1",
        "alice",
        MessageActorType.HUMAN,
        MessageDisposition.ACCEPTED,
        "first",
        "2026-01-01T00:00:00Z",
    )
    repository.upsert_message(
        thread.id,
        "2",
        "bot",
        MessageActorType.AGENT,
        MessageDisposition.IGNORED,
        "agent response",
        "2026-01-01T00:01:00Z",
    )
    task = repository.create(thread.id, TaskKind.INITIAL, (first,), 0)
    second = repository.upsert_message(
        thread.id,
        "3",
        "bob",
        MessageActorType.HUMAN,
        MessageDisposition.ACCEPTED,
        "second",
        "2026-01-01T00:02:00Z",
    )

    # WHEN
    repository.set_state(task.id, TaskState.SKIPPED, "superseded")
    repository.synchronize_source("repo", "github", ())

    # THEN
    assert repository.unassigned_messages(thread.id) == (second,)
    assert repository.get(task.id).state is TaskState.SKIPPED
    assert repository.get(task.id).reason == "superseded"
    assert not repository.thread(thread.id).eligible
    engine.dispose()
