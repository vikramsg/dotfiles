import json
import sqlite3

import pytest

from ocint.ctx.sql import run_ctx_sql
from ocint.opencode.repository import OpenCodeRepository

from tests.fixtures.opencode_db import create_opencode_db


def test_ctx_sql_installs_temporary_views(tmp_path) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")
    rows = run_ctx_sql(
        OpenCodeRepository(db_path),
        "SELECT provider, COUNT(*) AS sessions, MIN(workspace) AS workspace FROM ctx_sessions GROUP BY provider",
    )

    assert rows == [{"provider": "opencode", "sessions": 2, "workspace": "/work/repo-directory-only"}]


def test_ctx_sql_allows_select_star_from_ctx_sessions(tmp_path) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")

    rows = run_ctx_sql(OpenCodeRepository(db_path), "SELECT * FROM ctx_sessions ORDER BY session_id")

    assert [row["session_id"] for row in rows] == ["s-primary", "s-sub"]
    assert set(rows[0]) == {"provider", "provider_session_id", "session_id", "parent_id", "title", "workspace", "time_created", "time_updated"}


def test_ctx_sql_rejects_direct_non_history_base_table_read(tmp_path) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")

    with pytest.raises(sqlite3.DatabaseError):
        run_ctx_sql(OpenCodeRepository(db_path), "SELECT * FROM account")


def test_ctx_sql_rejects_direct_non_history_base_table_count(tmp_path) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")

    with pytest.raises(sqlite3.DatabaseError):
        run_ctx_sql(OpenCodeRepository(db_path), "SELECT COUNT(*) FROM account")


def test_ctx_sql_rejects_cte_shadowing_ctx_view_names(tmp_path) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")

    with pytest.raises(ValueError, match="shadow ctx views"):
        run_ctx_sql(OpenCodeRepository(db_path), "WITH ctx_sessions AS (SELECT * FROM account) SELECT COUNT(*) FROM ctx_sessions")


def test_ctx_sql_allows_non_shadowing_ctes_over_ctx_views(tmp_path) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")

    rows = run_ctx_sql(OpenCodeRepository(db_path), "WITH sessions AS (SELECT session_id FROM ctx_sessions) SELECT COUNT(*) AS sessions FROM sessions")

    assert rows == [{"sessions": 2}]


def test_ctx_sql_views_include_files_touched(tmp_path) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")
    rows = run_ctx_sql(
        OpenCodeRepository(db_path),
        """
        SELECT path FROM ctx_files_touched
        WHERE event_id = 'evt_native_patch'
        ORDER BY path
        """,
    )

    assert json.loads(json.dumps(rows)) == [
        {"path": "bin/ocint/ocint/ctx/search.py"},
        {"path": "bin/ocint/ocint/opencode/schema.py"},
        {"path": "bin/ocint/tests/ctx/test_sql.py"},
        {"path": "implementation_notes.md"},
    ]


def test_ctx_sql_maps_native_event_columns_and_payload_time(tmp_path) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")
    rows = run_ctx_sql(
        OpenCodeRepository(db_path),
        """
        SELECT provider_session_id, event_type, time_created
        FROM ctx_events
        WHERE event_id = 'evt_native_tool'
        """,
    )

    assert rows == [{"provider_session_id": "s-primary", "event_type": "tool.invocation", "time_created": 1704067200004}]


def test_ctx_sql_falls_back_to_payload_session_id_for_native_events(tmp_path) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")
    rows = run_ctx_sql(
        OpenCodeRepository(db_path),
        "SELECT provider_session_id FROM ctx_events WHERE event_id = 'evt_json_session'",
    )

    assert rows == [{"provider_session_id": "s-primary"}]


def test_ctx_sql_rejects_mutation(tmp_path) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")

    with pytest.raises((ValueError, Exception)):
        run_ctx_sql(OpenCodeRepository(db_path), "DROP TABLE session")
