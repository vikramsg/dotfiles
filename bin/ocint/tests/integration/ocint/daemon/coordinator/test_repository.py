from pathlib import Path

from ocint.daemon.db import create_daemon_engine, current_daemon_head_revision, migrate_daemon_db
from sqlalchemy import inspect


def test_additive_migration_keeps_old_tables_and_adds_coordinator_tables(tmp_path: Path) -> None:
    # GIVEN
    database = tmp_path / "daemon.sqlite"

    # WHEN
    migrate_daemon_db(database)
    engine = create_daemon_engine(database)
    tables = set(inspect(engine).get_table_names())

    # THEN
    assert current_daemon_head_revision() == "20260807_add_coordinator"
    assert {"job", "task", "slack_thread"}.issubset(tables)
    assert {
        "coordinator_event",
        "coordinator_conversation",
        "coordinator_turn",
        "coordinator_delivery",
    }.issubset(tables)
    engine.dispose()
