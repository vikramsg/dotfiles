import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from ocint.cli import main
from tests.support.opencode_db import create_opencode_db


def test_ctx_sql_queries_imported_views(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)

    rows = _sql_json(
        "SELECT provider, COUNT(*) AS sessions, MIN(workspace) AS workspace FROM ctx_sessions GROUP BY provider"
    )

    assert rows == [{"provider": "opencode", "sessions": 2, "workspace": "/work/repo-directory-only"}]


def test_ctx_sql_allows_select_star_from_ctx_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)

    rows = _sql_json("SELECT * FROM ctx_sessions ORDER BY session_id")

    assert [row["session_id"] for row in rows] == ["s-primary", "s-sub"]
    assert set(rows[0]) == {
        "provider",
        "provider_session_id",
        "session_id",
        "parent_id",
        "title",
        "workspace",
        "time_created",
        "time_updated",
    }


def test_ctx_sql_rejects_direct_internal_table_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(main, ["ctx", "sql", "SELECT * FROM ctx_event"])

    assert result.exit_code != 0


def test_ctx_sql_rejects_alembic_version_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(main, ["ctx", "sql", "SELECT * FROM alembic_version"])

    assert result.exit_code != 0


def test_ctx_sql_rejects_fts_table_read_without_leaking_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(main, ["ctx", "sql", "SELECT * FROM ctx_event_fts"])

    assert result.exit_code != 0
    assert "RAW_EVENT_ONLY_MARKER" not in result.output


def test_ctx_sql_rejects_nested_cte_payload_json_leak(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(
        main,
        [
            "ctx",
            "sql",
            """
            WITH outer_query AS (
              WITH ctx_events AS (SELECT payload_json FROM ctx_event)
              SELECT payload_json FROM ctx_events
            )
            SELECT payload_json FROM outer_query
            """,
        ],
    )

    assert result.exit_code != 0
    assert "sessionID" not in result.output


def test_ctx_sql_rejects_comment_obscured_nested_cte_alembic_version_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(
        main,
        [
            "ctx",
            "sql",
            """
            WITH outer_query AS (
              /* A nested shadowed stable-view name must not expose migration internals. */
              WITH ctx_sources AS (SELECT version_num FROM alembic_version)
              SELECT version_num FROM ctx_sources
            )
            SELECT version_num FROM outer_query
            """,
        ],
    )

    assert result.exit_code != 0
    assert "20260704_create_ctx_index" not in result.output


def test_ctx_sql_rejects_nested_cte_shadowing_stable_view_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(
        main,
        [
            "ctx",
            "sql",
            """
            WITH outer_query AS (
              WITH ctx_events AS (SELECT * FROM ctx_sessions)
              SELECT * FROM ctx_events
            )
            SELECT * FROM outer_query
            """,
        ],
    )

    assert result.exit_code != 0
    assert "shadow ctx views" in result.output


def test_ctx_sql_rejects_comment_obscured_cte_shadowing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(
        main,
        [
            "ctx",
            "sql",
            """
            WITH/* leading */ctx_sources/* name */AS/* as */(SELECT * FROM ctx_sessions)
            SELECT * FROM ctx_sources
            """,
        ],
    )

    assert result.exit_code != 0
    assert "shadow ctx views" in result.output


def test_ctx_sql_rejects_quoted_and_recursive_cte_shadowing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)
    runner = CliRunner()

    quoted = runner.invoke(
        main,
        ["ctx", "sql", 'WITH "ctx_files_touched" AS (SELECT * FROM ctx_sessions) SELECT * FROM "ctx_files_touched"'],
    )
    recursive = runner.invoke(
        main,
        ["ctx", "sql", "WITH RECURSIVE ctx_sessions AS (SELECT * FROM ctx_events) SELECT * FROM ctx_sessions"],
    )

    assert quoted.exit_code != 0
    assert "shadow ctx views" in quoted.output
    assert recursive.exit_code != 0
    assert "shadow ctx views" in recursive.output


def test_ctx_sql_rejects_cte_shadowing_ctx_view_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(
        main,
        ["ctx", "sql", "WITH ctx_sessions AS (SELECT * FROM ctx_event) SELECT COUNT(*) FROM ctx_sessions"],
    )

    assert result.exit_code != 0
    assert "shadow ctx views" in result.output


def test_ctx_sql_allows_non_shadowing_ctes_over_ctx_views(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)

    rows = _sql_json("WITH sessions AS (SELECT session_id FROM ctx_sessions) SELECT COUNT(*) AS sessions FROM sessions")

    assert rows == [{"sessions": 2}]


def test_ctx_sql_views_include_files_touched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)

    rows = _sql_json(
        """
        SELECT path FROM ctx_files_touched
        WHERE event_id = 'p-primary-patch'
        ORDER BY path
        """
    )

    assert rows == [
        {"path": "bin/ocint/ocint/ctx/search.py"},
        {"path": "bin/ocint/ocint/opencode/schema.py"},
        {"path": "bin/ocint/tests/integration/ctx/test_sql_workflow.py"},
        {"path": "implementation_notes.md"},
    ]


def test_ctx_sql_raw_output_format_reads_stable_views(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(main, ["ctx", "sql", "SELECT provider FROM ctx_sources", "--format", "raw"])

    assert result.exit_code == 0, result.output
    assert result.output == "opencode\n"


def test_ctx_sql_maps_message_part_columns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)

    rows = _sql_json(
        """
        SELECT provider_session_id, event_type, source_table, time_created
        FROM ctx_events
        WHERE event_id = 'p-primary-step'
        """
    )

    assert len(rows) == 1
    assert rows[0]["provider_session_id"] == "s-primary"
    assert rows[0]["event_type"] == "step-finish"
    assert rows[0]["source_table"] == "part"
    assert isinstance(rows[0]["time_created"], int)


def test_ctx_sql_events_view_contains_only_message_and_part_source_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _import_fixture(tmp_path, monkeypatch)

    rows = _sql_json(
        "SELECT source_table, COUNT(*) AS events FROM ctx_events GROUP BY source_table ORDER BY source_table"
    )

    assert [row["source_table"] for row in rows] == ["message", "part"]


def test_ctx_sql_rejects_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(main, ["ctx", "sql", "DROP TABLE ctx_session"])

    assert result.exit_code != 0


def _import_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))
    imported = CliRunner().invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "missing-opencode.db"))


def _sql_json(sql: str) -> list[dict[str, object]]:
    result = CliRunner().invoke(main, ["ctx", "sql", sql, "--format", "json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)
