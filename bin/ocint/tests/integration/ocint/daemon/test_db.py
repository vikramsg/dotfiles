import stat
from pathlib import Path

import pytest
from alembic import command
from ocint.daemon.db import create_daemon_engine, downgrade_daemon_db, migrate_daemon_db
from ocint.daemon.db.connection import alembic_config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def test_upgrade_downgrade_upgrade_occurs(tmp_path: Path) -> None:
    # GIVEN
    database = tmp_path / "control.sqlite"

    # WHEN
    migrate_daemon_db(database)
    downgrade_daemon_db(database)
    migrate_daemon_db(database)


def test_migration_secures_existing_database_without_recreating_it(tmp_path: Path) -> None:
    # GIVEN
    database = tmp_path / "control.sqlite"
    migrate_daemon_db(database)
    inode = database.stat().st_ino
    database.chmod(0o644)

    # WHEN
    migrate_daemon_db(database)

    # THEN
    assert database.stat().st_ino == inode
    assert stat.S_IMODE(database.stat().st_mode) == 0o600


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
