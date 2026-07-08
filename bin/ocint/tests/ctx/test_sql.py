import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from ocint.cli import main
from sqlalchemy import create_engine, text
from tests.fixtures.opencode_db import create_opencode_db


def test_ctx_sql_queries_imported_views(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)

    rows = _sql_json(
        "SELECT provider, COUNT(*) AS sessions, MIN(workspace) AS workspace FROM ctx_sessions GROUP BY provider"
    )

    assert rows == [{"provider": "opencode", "sessions": 2, "workspace": "/work/repo-directory-only"}]


@pytest.mark.parametrize("backend", ["sqlite", "duckdb"])
def test_ctx_sql_is_stable_view_only_for_backend(backend: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if backend == "duckdb":
        _skip_if_duckdb_fts_unavailable(tmp_path)
    _import_fixture(tmp_path, monkeypatch, backend=backend)

    rows = _sql_json("SELECT COUNT(*) AS sessions FROM ctx_sessions", backend=backend)
    rejected = CliRunner().invoke(main, ["ctx", "--backend", backend, "sql", "SELECT * FROM ctx_event"])

    assert rows == [{"sessions": 2}]
    assert rejected.exit_code != 0


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
    assert "0001_ctx_index" not in result.output


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
        WHERE event_id = 'evt_native_patch'
        ORDER BY path
        """
    )

    assert rows == [
        {"path": "bin/ocint/ocint/ctx/search.py"},
        {"path": "bin/ocint/ocint/opencode/schema.py"},
        {"path": "bin/ocint/tests/ctx/test_sql.py"},
        {"path": "implementation_notes.md"},
    ]


def test_ctx_sql_maps_native_event_columns_and_payload_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)

    rows = _sql_json(
        """
        SELECT provider_session_id, event_type, time_created
        FROM ctx_events
        WHERE event_id = 'evt_native_tool'
        """
    )

    assert len(rows) == 1
    assert rows[0]["provider_session_id"] == "s-primary"
    assert rows[0]["event_type"] == "tool.invocation"
    assert isinstance(rows[0]["time_created"], int)


def test_ctx_sql_falls_back_to_payload_session_id_for_native_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _import_fixture(tmp_path, monkeypatch)

    rows = _sql_json("SELECT provider_session_id FROM ctx_events WHERE event_id = 'evt_json_session'")

    assert rows == [{"provider_session_id": "s-primary"}]


def test_ctx_sql_rejects_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(main, ["ctx", "sql", "DROP TABLE ctx_session"])

    assert result.exit_code != 0


def _import_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, backend: str = "sqlite") -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))
    monkeypatch.setenv("OCINT_CTX_DUCKDB", str(tmp_path / "ctx.duckdb"))
    imported = CliRunner().invoke(main, ["ctx", "--backend", backend, "import"])
    assert imported.exit_code == 0, imported.output
    monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "missing-opencode.db"))


def _sql_json(sql: str, *, backend: str = "sqlite") -> list[dict[str, object]]:
    result = CliRunner().invoke(main, ["ctx", "--backend", backend, "sql", sql, "--format", "json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _skip_if_duckdb_fts_unavailable(tmp_path: Path) -> None:
    try:
        extension_dir = tmp_path / "duckdb_extensions"
        extension_dir.mkdir(parents=True, exist_ok=True)
        engine = create_engine(f"duckdb:///{tmp_path / 'fts-check.duckdb'}")
        with engine.begin() as connection:
            connection.execute(text(f"SET extension_directory='{extension_dir.as_posix()}'"))
            connection.execute(text("INSTALL fts"))
            connection.execute(text("LOAD fts"))
    except Exception as error:  # pragma: no cover - environment-dependent extension availability
        pytest.skip(f"DuckDB FTS extension is unavailable: {error}")
    finally:
        if "engine" in locals():
            engine.dispose()
