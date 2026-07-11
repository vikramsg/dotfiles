import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from ocint._timeutil import make_window
from ocint.opencode.repository import OpenCodeRepository
from ocint.state.service import StateService
from tests.fixtures.opencode_db import create_opencode_db


def test_state_summary_uses_authoritative_session_aggregates_and_counts_messages(tmp_path: Path) -> None:
    # GIVEN session aggregates that deliberately differ from step-finish part payloads
    db_path = create_opencode_db(tmp_path / "opencode.db")
    service = StateService(OpenCodeRepository(db_path))

    # WHEN all-time usage is summarized
    summary = service.summary(make_window())

    # THEN only physical session aggregates are used and message records are counted
    assert summary.sessions == 2
    assert summary.messages == 2
    assert summary.cost == 30.0
    assert summary.tokens.input == 101
    assert summary.tokens.output == 202
    assert summary.tokens.reasoning == 33
    assert summary.tokens.cache_read == 44
    assert summary.tokens.cache_write == 55
    assert summary.tokens.total == 435


def test_recently_updated_session_includes_its_lifetime_aggregates(tmp_path: Path) -> None:
    # GIVEN an old session whose updated time falls inside the requested rolling window
    db_path = create_opencode_db(tmp_path / "opencode.db")
    now = datetime(2026, 7, 11, 12, tzinfo=UTC)
    old = int((now - timedelta(days=100)).timestamp() * 1000)
    recent = int((now - timedelta(hours=1)).timestamp() * 1000)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE session SET time_created = ?, time_updated = ? WHERE id = 's-primary'", (old, recent)
        )
        connection.execute("UPDATE session SET time_updated = ? WHERE id = 's-sub'", (old,))

    # WHEN sessions are filtered by one rolling 24-hour period
    rows = StateService(OpenCodeRepository(db_path)).sessions(make_window(days=1, now=now))

    # THEN the qualifying session retains its complete lifetime aggregates
    assert len(rows) == 1
    assert rows[0].session_id == "s-primary"
    assert rows[0].messages == 1
    assert rows[0].cost == 10.0
    assert rows[0].tokens.total == 420
    assert rows[0].first_seen == datetime.fromtimestamp(old / 1000, tz=UTC)
    assert rows[0].last_seen == datetime.fromtimestamp(recent / 1000, tz=UTC)


def test_days_is_a_rolling_multiple_of_24_hours() -> None:
    # GIVEN a fixed current instant
    now = datetime(2026, 7, 11, 15, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))

    # WHEN a two-day window is made
    window = make_window(days=2, now=now)

    # THEN its boundary is exactly 48 hours before the current instant
    assert window.start_ms == int((now - timedelta(hours=48)).timestamp() * 1000)
    assert window.label == "last 2 days"


def test_days_zero_starts_at_local_midnight() -> None:
    # GIVEN a fixed local current instant
    now = datetime(2026, 7, 11, 15, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))

    # WHEN a zero-day window is made
    window = make_window(days=0, now=now)

    # THEN its boundary is midnight in the same local timezone
    assert window.start_ms == int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    assert window.label == "today"


def test_omitted_days_is_all_time() -> None:
    # GIVEN no day restriction
    # WHEN the usage window is made
    window = make_window()

    # THEN no lower time boundary is applied
    assert window.start_ms is None
    assert window.label == "all"


@pytest.mark.parametrize(
    ("table", "column", "expected"),
    [
        ("session", "tokens_input", "OpenCode session table is missing required columns: tokens_input"),
        ("message", "session_id", "OpenCode message table is missing required columns: session_id"),
    ],
)
def test_state_usage_fails_clearly_when_required_columns_are_missing(
    tmp_path: Path, table: str, column: str, expected: str
) -> None:
    # GIVEN an OpenCode-shaped database missing one required physical column
    source = create_opencode_db(tmp_path / "source.db")
    broken = tmp_path / "broken.db"
    with sqlite3.connect(source) as source_connection, sqlite3.connect(broken) as broken_connection:
        source_connection.backup(broken_connection)
        broken_connection.execute(f"ALTER TABLE {table} DROP COLUMN {column}")

    # WHEN authoritative usage is requested
    # THEN the absent contract column is reported instead of falling back to JSON
    with pytest.raises(ValueError, match=expected):
        StateService(OpenCodeRepository(broken)).summary(make_window())
