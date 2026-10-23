from pathlib import Path

import pytest
from alembic import command
from ocint.daemon.db import create_daemon_engine, current_daemon_head_revision, migrate_daemon_db
from ocint.daemon.db.connection import alembic_config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError


def test_additive_migration_keeps_old_tables_and_adds_coordinator_tables(tmp_path: Path) -> None:
    # GIVEN
    database = tmp_path / "daemon.sqlite"

    # WHEN
    migrate_daemon_db(database)
    engine = create_daemon_engine(database)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    message_identity = next(
        constraint
        for constraint in inspector.get_unique_constraints("coordinator_event")
        if constraint["name"] == "uq_coordinator_event_message"
    )

    # THEN
    assert current_daemon_head_revision() == "20260810_complete_coordinator_message_identity"
    assert {"job", "task", "slack_thread"}.issubset(tables)
    assert {
        "coordinator_event",
        "coordinator_conversation",
        "coordinator_turn",
        "coordinator_delivery",
    }.issubset(tables)
    assert message_identity["column_names"] == ["provider", "workspace_id", "channel_id", "thread_id", "message_id"]
    engine.dispose()


def test_message_identity_migration_preserves_rows_and_foreign_keys(tmp_path: Path) -> None:
    # GIVEN
    database = tmp_path / "daemon.sqlite"
    command.upgrade(alembic_config(database), "20260807_add_coordinator")
    engine = create_daemon_engine(database)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO coordinator_conversation "
                "(id, provider, workspace_id, channel_id, thread_id, state, opencode_session_id, created_at, updated_at) "
                "VALUES (1, 'chat', 'workspace', 'channel', 'thread-one', 'active', '', 'now', 'now')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO coordinator_event "
                "(event_id, provider, workspace_id, channel_id, thread_id, message_id, actor_id, text, "
                "source_created_at, source_order_at, message_kind, managed_prompt, disposition, created_at) "
                "VALUES ('event-one', 'chat', 'workspace', 'channel', 'thread-one', 'message', 'actor', 'hello', "
                "'source-time', 1, 'root', 'prompt', 'accepted', 'now')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO coordinator_turn "
                "(id, event_id, conversation_id, source_order_at, source_order_tiebreaker, state, managed_prompt, "
                "opencode_user_message_id, assistant_message_id, response_text, error, retry_count, retry_not_before, "
                "created_at, updated_at) VALUES "
                "(1, 'event-one', 1, 1, 'message', 'received', 'prompt', 'user-message', '', '', '', 0, '', 'now', 'now')"
            )
        )
    engine.dispose()

    # WHEN
    migrate_daemon_db(database)

    # THEN
    engine = create_daemon_engine(database)
    turn_foreign_keys = inspect(engine).get_foreign_keys("coordinator_turn")
    with engine.begin() as connection:
        assert connection.execute(text("SELECT event_id FROM coordinator_event")).scalar_one() == "event-one"
        assert connection.execute(text("SELECT event_id FROM coordinator_turn")).scalar_one() == "event-one"
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        assert any(
            foreign_key["referred_table"] == "coordinator_event" and foreign_key["constrained_columns"] == ["event_id"]
            for foreign_key in turn_foreign_keys
        )
        connection.execute(
            text(
                "INSERT INTO coordinator_event "
                "(event_id, provider, workspace_id, channel_id, thread_id, message_id, actor_id, text, "
                "source_created_at, source_order_at, message_kind, managed_prompt, disposition, created_at) "
                "VALUES ('event-two', 'chat', 'workspace', 'channel', 'thread-two', 'message', 'actor', 'hello', "
                "'source-time', 2, 'root', 'prompt', 'accepted', 'now')"
            )
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO coordinator_event "
                    "(event_id, provider, workspace_id, channel_id, thread_id, message_id, actor_id, text, "
                    "source_created_at, source_order_at, message_kind, managed_prompt, disposition, created_at) "
                    "VALUES ('event-three', 'chat', 'workspace', 'channel', 'thread-two', 'message', 'actor', 'hello', "
                    "'source-time', 3, 'reply', 'prompt', 'accepted', 'now')"
                )
            )
    engine.dispose()
