import re
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


def test_detailed_groups_assistant_message_data_by_project_and_historical_agent(tmp_path: Path) -> None:
    # GIVEN session aggregates and current session agents that differ from assistant message data
    db_path = create_opencode_db(tmp_path / "opencode.db")
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE session SET data = '{\"agent\": \"later-root-agent\"}' WHERE id = 's-primary'")
        connection.execute("UPDATE session SET data = '{\"agent\": \"later-subagent\"}' WHERE id = 's-sub'")
    service = StateService(OpenCodeRepository(db_path))

    # WHEN all assistant-message usage is detailed
    detailed = service.detailed(make_window())
    summary = service.summary(make_window())

    # THEN project joins and immutable message agents form matching, deliberately divergent groups
    assert detailed.message_attributed_cost == 43.0
    assert detailed.message_attributed_cost != summary.cost
    assert [(row.project_id, row.worktree, row.cost) for row in detailed.projects] == [
        ("project-automation", "/work/automation", 31.0),
        ("project-dotfiles", "/work/dotfiles", 12.0),
    ]
    assert [(row.agent, row.kind, row.sessions, row.assistant_messages, row.cost) for row in detailed.agents] == [
        ("historical-agent", "subagent", 1, 1, 31.0),
        ("historical-agent", "root", 1, 1, 12.0),
    ]
    assert [
        (row.project_id, row.worktree, row.agent, row.kind, row.sessions, row.assistant_messages, row.cost)
        for row in detailed.project_agents
    ] == [
        ("project-automation", "/work/automation", "historical-agent", "subagent", 1, 1, 31.0),
        ("project-dotfiles", "/work/dotfiles", "historical-agent", "root", 1, 1, 12.0),
    ]
    assert all("later-" not in row.agent for row in detailed.agents)
    assert detailed.projects[1].tokens.total == 42
    assert detailed.agents[1].tokens.total == 42
    assert detailed.project_agents[1].tokens.total == 42
    assert sum(row.cost for row in detailed.projects) == detailed.message_attributed_cost
    assert sum(row.cost for row in detailed.agents) == detailed.message_attributed_cost
    assert sum(row.cost for row in detailed.project_agents) == detailed.message_attributed_cost


def test_detailed_days_filters_message_creation_not_session_update(tmp_path: Path) -> None:
    # GIVEN a recently created assistant message in sessions whose update times are old
    db_path = create_opencode_db(tmp_path / "opencode.db")
    now = datetime(2026, 7, 11, 12, tzinfo=UTC)
    old = int((now - timedelta(days=3)).timestamp() * 1000)
    recent = int((now - timedelta(hours=1)).timestamp() * 1000)
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE session SET time_updated = ?", (old,))
        connection.execute("UPDATE message SET time_created = ? WHERE id = 'm-primary'", (recent,))
        connection.execute("UPDATE message SET time_created = ? WHERE id = 'm-sub'", (old,))
    service = StateService(OpenCodeRepository(db_path))
    window = make_window(days=1, now=now)

    # WHEN the shared rolling window is applied
    detailed = service.detailed(window)
    summary = service.summary(window)

    # THEN detailed includes the recent message while session-authoritative summary includes no stale sessions
    assert detailed.message_attributed_cost == 12.0
    assert [row.project_id for row in detailed.projects] == ["project-dotfiles"]
    assert summary.sessions == 0


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


@pytest.mark.parametrize(
    ("table", "column", "expected"),
    [
        ("message", "id", "OpenCode message table is missing required columns: id"),
        ("message", "session_id", "OpenCode message table is missing required columns: session_id"),
        ("message", "time_created", "OpenCode message table is missing required columns: time_created"),
        ("message", "data", "OpenCode message table is missing required columns: data"),
        ("session", "id", "OpenCode session table is missing required columns: id"),
        ("session", "project_id", "OpenCode session table is missing required columns: project_id"),
        ("session", "parent_id", "OpenCode session table is missing required columns: parent_id"),
        ("project", "id", "OpenCode project table is missing required columns: id"),
        ("project", "worktree", "OpenCode project table is missing required columns: worktree"),
    ],
)
def test_detailed_fails_clearly_when_current_source_columns_are_missing(
    tmp_path: Path, table: str, column: str, expected: str
) -> None:
    # GIVEN a current-schema fixture whose detailed source column was renamed away
    db_path = create_opencode_db(tmp_path / "opencode.db")
    with sqlite3.connect(db_path) as connection:
        connection.execute(f"ALTER TABLE {table} RENAME COLUMN {column} TO {column}_old")

    # WHEN detailed message attribution is requested
    # THEN it fails rather than using an old-schema fallback
    with pytest.raises(ValueError, match=expected):
        StateService(OpenCodeRepository(db_path)).detailed(make_window())


@pytest.mark.parametrize(
    "agent_expression",
    [
        pytest.param("json_remove(data, '$.agent')", id="missing"),
        pytest.param("json_set(data, '$.agent', json('null'))", id="null"),
        pytest.param("json_set(data, '$.agent', '')", id="empty"),
        pytest.param("json_set(data, '$.agent', '   ')", id="whitespace"),
        pytest.param("json_set(data, '$.agent', char(9) || char(10))", id="whitespace-control"),
        pytest.param("json_set(data, '$.agent', 1)", id="non-text"),
    ],
)
def test_detailed_rejects_invalid_historical_agent_identity(tmp_path: Path, agent_expression: str) -> None:
    # GIVEN a current-schema assistant message with an invalid historical agent identity
    db_path = create_opencode_db(tmp_path / "opencode.db")
    with sqlite3.connect(db_path) as connection:
        connection.execute(f"UPDATE message SET data = {agent_expression} WHERE id = 'm-primary'")

    # WHEN detailed message attribution is requested
    # THEN it identifies the invalid source message instead of coercing an agent label
    with pytest.raises(
        ValueError,
        match=re.escape("OpenCode assistant message has invalid historical agent identity: m-primary"),
    ):
        StateService(OpenCodeRepository(db_path)).detailed(make_window())


def test_state_status_documentation_records_summary_and_detailed_accounting() -> None:
    # GIVEN the state accounting documentation
    status_doc = (Path(__file__).parents[2] / "docs" / "spec" / "status.md").read_text()

    # WHEN its accounting contract is read
    # THEN it distinguishes source data, cutoffs, and the observed divergence
    assert "SUM(session.cost)" in status_doc
    assert "session.time_updated" in status_doc
    assert "message.data.cost" in status_doc
    assert "message.time_created" in status_doc
    assert "project/agent" in status_doc
    assert "project, agent, and project/agent" in status_doc
    assert "## Window Semantics" in status_doc
    assert "older messages belonging to recently updated sessions" in status_doc
    assert "$5107.520334" in status_doc
    assert "$5142.157824" in status_doc
