import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command
from ocint.daemon.db import create_daemon_engine, downgrade_daemon_db, migrate_daemon_db
from ocint.daemon.db.connection import alembic_config
from ocint.daemon.github.repository import GitHubRepository
from ocint.daemon.models import GitHubLogin, MessageClassification
from ocint.daemon.pull_request_job import PullRequestJobRequest
from ocint.daemon.pull_request_job.repository import PullRequestJobRepository
from ocint.daemon.tasks.models import TaskKind
from ocint.daemon.tasks.repository import TaskRepository
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def test_upgrade_downgrade_upgrade_occurs(tmp_path: Path) -> None:
    # GIVEN
    database = tmp_path / "control.sqlite"

    # WHEN
    migrate_daemon_db(database)
    downgrade_daemon_db(database)
    migrate_daemon_db(database)


def test_migration_rejects_non_private_database_without_mutating_it(tmp_path: Path) -> None:
    # GIVEN
    database = tmp_path / "control.sqlite"
    database.write_text("preserve")
    database.chmod(0o644)
    metadata = database.stat()

    # WHEN / THEN
    with pytest.raises(PermissionError, match="user-owned regular mode-0600"):
        migrate_daemon_db(database)
    assert database.read_text() == "preserve"
    assert database.stat().st_ino == metadata.st_ino
    assert stat.S_IMODE(database.stat().st_mode) == 0o644


def test_engine_creates_private_database_before_sqlite_connects(tmp_path: Path) -> None:
    # GIVEN
    database = tmp_path / "control.sqlite"

    # WHEN
    engine = create_daemon_engine(database)

    # THEN
    assert database.is_file()
    assert database.stat().st_uid == os.getuid()
    assert stat.S_IMODE(database.stat().st_mode) == 0o600
    engine.dispose()


def test_engine_rejects_non_regular_database_without_mutating_it(tmp_path: Path) -> None:
    # GIVEN
    database = tmp_path / "control.sqlite"
    os.mkfifo(database, mode=0o600)
    metadata = database.stat()

    # WHEN / THEN
    with pytest.raises(PermissionError, match="user-owned regular mode-0600"):
        create_daemon_engine(database)
    assert stat.S_ISFIFO(database.stat().st_mode)
    assert database.stat().st_ino == metadata.st_ino
    assert stat.S_IMODE(database.stat().st_mode) == 0o600


def test_engine_rejects_foreign_owner_without_mutating_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # GIVEN
    database = tmp_path / "control.sqlite"
    database.write_text("preserve")
    database.chmod(0o600)
    metadata = database.stat()
    monkeypatch.setattr("ocint.daemon.db.connection.os.getuid", lambda: metadata.st_uid + 1)

    # WHEN / THEN
    with pytest.raises(PermissionError, match="user-owned regular mode-0600"):
        create_daemon_engine(database)
    assert database.read_text() == "preserve"
    assert database.stat().st_ino == metadata.st_ino
    assert stat.S_IMODE(database.stat().st_mode) == 0o600


def test_migration_uses_persistent_canonical_private_lock(tmp_path: Path) -> None:
    # GIVEN
    canonical_directory = tmp_path / "canonical"
    canonical_directory.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(canonical_directory, target_is_directory=True)
    database = alias / "control.sqlite"

    # WHEN
    migrate_daemon_db(database)
    lock = canonical_directory / "control.sqlite.migrate.lock"
    metadata = lock.stat()
    migrate_daemon_db(database)

    # THEN
    assert lock.is_file()
    assert metadata.st_uid == os.getuid()
    assert stat.S_IMODE(metadata.st_mode) == 0o600
    assert lock.stat().st_ino == metadata.st_ino


def test_migration_rejects_non_private_lock(tmp_path: Path) -> None:
    # GIVEN
    database = tmp_path / "control.sqlite"
    lock = tmp_path / "control.sqlite.migrate.lock"
    lock.touch(mode=0o600)
    lock.chmod(0o640)

    # WHEN / THEN
    with pytest.raises(PermissionError, match="user-owned regular mode-0600"):
        migrate_daemon_db(database)
    assert not database.exists()


def test_migration_does_not_follow_lock_symlink(tmp_path: Path) -> None:
    # GIVEN
    database = tmp_path / "control.sqlite"
    target = tmp_path / "unrelated"
    target.write_text("preserve")
    target.chmod(0o600)
    lock = tmp_path / "control.sqlite.migrate.lock"
    lock.symlink_to(target)

    # WHEN / THEN
    with pytest.raises(PermissionError, match="must not be a symbolic link"):
        migrate_daemon_db(database)
    assert target.read_text() == "preserve"
    assert not database.exists()


def test_engine_rejects_database_file_symlink_without_touching_target(tmp_path: Path) -> None:
    # GIVEN
    target = tmp_path / "preserved.sqlite"
    target.write_text("preserved database bytes")
    target.chmod(0o640)
    configured = tmp_path / "configured.sqlite"
    configured.symlink_to(target)

    # WHEN / THEN
    with pytest.raises(PermissionError, match="database file must not be a symbolic link"):
        create_daemon_engine(configured)
    assert target.read_text() == "preserved database bytes"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_engine_revalidates_before_wal_when_database_is_replaced_by_a_symlink(tmp_path: Path) -> None:
    # GIVEN
    database = tmp_path / "configured.sqlite"
    engine = create_daemon_engine(database)
    original = tmp_path / "original.sqlite"
    database.rename(original)
    target = tmp_path / "preserved.sqlite"
    target.write_text("preserved database bytes")
    target.chmod(0o640)
    database.symlink_to(target)

    # WHEN / THEN
    with pytest.raises(PermissionError, match="must not be a symbolic link"):
        engine.connect()
    assert target.read_text() == "preserved database bytes"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    engine.dispose()


def test_migration_rejects_database_file_symlink_without_touching_target(tmp_path: Path) -> None:
    # GIVEN
    target = tmp_path / "preserved.sqlite"
    target.write_text("preserved database bytes")
    target.chmod(0o640)
    configured = tmp_path / "configured.sqlite"
    configured.symlink_to(target)

    # WHEN / THEN
    with pytest.raises(PermissionError, match="database file must not be a symbolic link"):
        migrate_daemon_db(configured)
    assert target.read_text() == "preserved database bytes"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert not (tmp_path / "preserved.sqlite.migrate.lock").exists()


def test_separate_process_migrations_are_serialized_by_one_lock(tmp_path: Path) -> None:
    # GIVEN
    database = tmp_path / "control.sqlite"
    invocation = (
        "from pathlib import Path; "
        "from ocint.daemon.db import migrate_daemon_db; "
        "import sys; "
        "migrate_daemon_db(Path(sys.argv[1]))"
    )

    # WHEN
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", invocation, str(database)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _index in range(2)
    ]
    results = [process.communicate(timeout=30) for process in processes]

    # THEN
    assert [(process.returncode, stderr) for process, (_stdout, stderr) in zip(processes, results, strict=True)] == [
        (0, ""),
        (0, ""),
    ]
    lock = tmp_path / "control.sqlite.migrate.lock"
    assert lock.exists()
    engine = create_daemon_engine(database)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM alembic_version")).scalar_one() == 1
    engine.dispose()


def test_thread_model_migration_discards_workflow_rows_and_preserves_jobs(tmp_path: Path) -> None:
    # GIVEN
    database = tmp_path / "control.sqlite"
    command.upgrade(alembic_config(database), "20260719_add_thread_execution_job")
    engine = create_daemon_engine(database)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO job VALUES ('preserved', 'keep', 'alice', 'repo', 'work', 'queued', 'execution', "
                "'', '', '', '', '', 0, 0, '', 0, '', '', 'now', 'now')"
            )
        )
        connection.execute(
            text("INSERT INTO thread VALUES (1, 'repo', 'github', '5', 'alice', 1, '', 'Title', 'Body', 'now', 'now')")
        )
        connection.execute(
            text(
                "INSERT INTO thread_message VALUES "
                "(1, 1, '10', 'alice', 'human', 'accepted', 'comment', 'now', 'now', 'now')"
            )
        )
        connection.execute(text("INSERT INTO task VALUES (1, 1, 'initial', 'unresolved', 0, '', 'now', 'now')"))
        connection.execute(text("INSERT INTO task_message VALUES (1, 1)"))
        connection.execute(
            text("INSERT INTO task_job VALUES (1, :job_id, 1)"),
            {"job_id": "preserved"},
        )
        connection.execute(text("INSERT INTO github_issue VALUES (1, 'owner/repo', 50, 5, 0, '')"))
        connection.execute(text("INSERT INTO github_issue_comment VALUES (10, 1, '')"))
    engine.dispose()

    # WHEN
    migrate_daemon_db(database)

    # THEN
    engine = create_daemon_engine(database)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM job")).scalar_one() == "preserved"
        for table in (
            "thread",
            "thread_message",
            "task",
            "task_message",
            "task_job",
            "github_issue",
            "github_issue_comment",
        ):
            assert connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0
    engine.dispose()


def test_migrated_message_source_identity_is_global(tmp_path: Path) -> None:
    # GIVEN
    database = tmp_path / "control.sqlite"
    migrate_daemon_db(database)
    engine = create_daemon_engine(database)

    # WHEN
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO thread (id, source_id, configured_repository, eligible, title) "
                "VALUES (1, 'thread:1', 'repo', 1, 'One')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO thread (id, source_id, configured_repository, eligible, title) "
                "VALUES (2, 'thread:2', 'repo', 1, 'Two')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO thread_message "
                "(id, thread_id, source_id, actor, classification, body, source_created_at, created_at, updated_at) "
                "VALUES (1, 1, 'message:1', 'alice', 'actionable', 'one', 'source-time', 'now', 'now')"
            )
        )

        # THEN
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO thread_message "
                    "(id, thread_id, source_id, actor, classification, body, source_created_at, created_at, updated_at) "
                    "VALUES (2, 2, 'message:1', 'bob', 'actionable', 'two', 'source-time', 'now', 'now')"
                )
            )
    engine.dispose()


def test_job_title_migration_downgrades_with_attached_task(tmp_path: Path) -> None:
    # GIVEN
    database = tmp_path / "control.sqlite"
    migrate_daemon_db(database)
    engine = create_daemon_engine(database)
    control = PullRequestJobRepository(engine)
    tasks = TaskRepository(engine)
    thread = tasks.upsert_thread("source:thread", "Work title", "repo", True)
    tasks.upsert_message(
        thread.id,
        "source:message",
        GitHubLogin("actor"),
        MessageClassification.ACTIONABLE,
        "work",
        "2026-07-24T00:00:00Z",
    )
    task = tasks.create_pending(thread.id, TaskKind.INITIAL, 0)
    assert task is not None
    job = control.submit(
        PullRequestJobRequest(
            idempotency_key="job",
            actor=GitHubLogin("actor"),
            repository="repo",
            title="Work title",
            prompt="work",
        )
    )
    tasks.attach_job(task.id, job.id)
    engine.dispose()

    # WHEN
    command.downgrade(alembic_config(database), "20260724_decouple_github_source_state")

    # THEN
    engine = create_daemon_engine(database)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT job_id FROM task_job")).scalar_one() == job.id
        columns = connection.execute(text("PRAGMA table_info(job)")).mappings()
        assert "title" not in {str(column["name"]) for column in columns}
    engine.dispose()


def test_slack_migration_preserves_workflow_and_backfills_pull_request_ownership(tmp_path: Path) -> None:
    # GIVEN
    database = tmp_path / "control.sqlite"
    command.upgrade(alembic_config(database), "20260724_add_job_title")
    engine = create_daemon_engine(database)
    control = PullRequestJobRepository(engine)
    tasks = TaskRepository(engine)
    github = GitHubRepository(engine)
    thread = tasks.upsert_thread("github:owner/repo:50", "Work title", "repo", True)
    tasks.upsert_message(
        thread.id, "github:owner/repo:issue:50", GitHubLogin("actor"), MessageClassification.ACTIONABLE, "work", "now"
    )
    task = tasks.create_pending(thread.id, TaskKind.INITIAL, 0)
    assert task is not None
    job = control.submit(
        PullRequestJobRequest(
            idempotency_key="job", actor=GitHubLogin("actor"), repository="repo", title="Work title", prompt="work"
        )
    )
    tasks.attach_job(task.id, job.id)
    issue = github.upsert_issue("github:owner/repo:50", "github:owner/repo:issue:50", "repo", "owner/repo", 50, 5, True)
    github.set_pull_request(issue.source_id, 7, "https://example.test/pull/7")
    engine.dispose()

    # WHEN
    migrate_daemon_db(database)

    # THEN
    engine = create_daemon_engine(database)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM task")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM task_job")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM github_issue")).scalar_one() == 1
        assert connection.execute(
            text("SELECT source_thread_id, repository, number, url FROM pull_request_ownership")
        ).one() == (
            "github:owner/repo:50",
            "owner/repo",
            7,
            "https://example.test/pull/7",
        )
    engine.dispose()
