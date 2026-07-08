import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner
from ocint.cli import main
from sqlalchemy import create_engine, text
from tests.fixtures.opencode_db import create_opencode_db


def test_ctx_import_creates_index_and_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    runner = CliRunner()

    first = runner.invoke(main, ["ctx", "import"])
    assert first.exit_code == 0, first.output
    assert "SESSIONS_SEEN" in first.output
    assert ctx_db.exists()

    counts_after_first = _ctx_counts(ctx_db)
    second = runner.invoke(main, ["ctx", "import"])
    assert second.exit_code == 0, second.output
    assert _ctx_counts(ctx_db) == counts_after_first
    assert counts_after_first["alembic_version"] == 1
    assert counts_after_first["ctx_event_fts"] > 0
    assert counts_after_first["ctx_session"] == 2
    assert counts_after_first["ctx_event"] > 0
    assert counts_after_first["ctx_file_touched"] > 0


def test_ctx_duckdb_import_creates_selected_backend_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _skip_if_duckdb_fts_unavailable(tmp_path)
    source_db = create_opencode_db(tmp_path / "opencode.db")
    sqlite_ctx = tmp_path / "ctx.sqlite"
    duckdb_ctx = tmp_path / "ctx.duckdb"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_BACKEND", "duckdb")
    monkeypatch.setenv("OCINT_CTX_DB", str(sqlite_ctx))
    monkeypatch.setenv("OCINT_CTX_DUCKDB", str(duckdb_ctx))

    result = CliRunner().invoke(main, ["ctx", "import", "--source-db", str(source_db), "--json"])

    assert result.exit_code == 0, result.output
    assert duckdb_ctx.exists()
    assert not sqlite_ctx.exists()
    status = CliRunner().invoke(main, ["ctx", "status", "--json"])
    assert status.exit_code == 0, status.output
    assert '"sessions": 2' in status.output
    rows = CliRunner().invoke(main, ["ctx", "sql", "SELECT COUNT(*) AS sessions FROM ctx_sessions", "--format", "json"])
    assert rows.exit_code == 0, rows.output
    assert json.loads(rows.output) == [{"sessions": 2}]


def test_ctx_backend_cli_option_overrides_environment_for_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _skip_if_duckdb_fts_unavailable(tmp_path)
    source_db = create_opencode_db(tmp_path / "opencode.db")
    duckdb_ctx = tmp_path / "ctx.duckdb"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_BACKEND", "sqlite")
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))
    monkeypatch.setenv("OCINT_CTX_DUCKDB", str(duckdb_ctx))
    imported = CliRunner().invoke(main, ["ctx", "--backend", "duckdb", "import", "--source-db", str(source_db)])
    assert imported.exit_code == 0, imported.output

    status = CliRunner().invoke(main, ["ctx", "--backend", "duckdb", "status", "--json"])

    assert status.exit_code == 0, status.output
    assert str(duckdb_ctx) in status.output


def test_ctx_compare_reports_benchmarks_and_speed_ratios(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _skip_if_duckdb_fts_unavailable(tmp_path)
    source_db = create_opencode_db(tmp_path / "opencode.db")
    sqlite_ctx = tmp_path / "compare.sqlite"
    duckdb_ctx = tmp_path / "compare.duckdb"
    monkeypatch.setenv("OCINT_CTX_DB", str(sqlite_ctx))
    monkeypatch.setenv("OCINT_CTX_DUCKDB", str(duckdb_ctx))

    result = CliRunner().invoke(
        main,
        [
            "ctx",
            "compare",
            "native event marker",
            "--source-db",
            str(source_db),
            "--sqlite-db",
            str(sqlite_ctx),
            "--duckdb-db",
            str(duckdb_ctx),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert '"backend": "sqlite"' in result.output
    assert '"backend": "duckdb"' in result.output
    assert '"speed_ratios"' in result.output
    assert '"write_ms"' in result.output
    assert '"search_ms"' in result.output


def test_ctx_compare_requires_explicit_backend_paths_and_does_not_create_default_indexes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    env_sqlite = tmp_path / "sentinel-default.sqlite"
    env_duckdb = tmp_path / "sentinel-default.duckdb"
    xdg_state = tmp_path / "xdg-state"
    xdg_sqlite = xdg_state / "ocint" / "ctx.sqlite"
    xdg_duckdb = xdg_state / "ocint" / "ctx.duckdb"
    monkeypatch.setenv("OCINT_CTX_DB", str(env_sqlite))
    monkeypatch.setenv("OCINT_CTX_DUCKDB", str(env_duckdb))
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg_state))

    result = CliRunner().invoke(
        main,
        ["ctx", "compare", "native event marker", "--source-db", str(source_db)],
    )

    assert result.exit_code != 0
    assert "--sqlite-db" in result.output or "--duckdb-db" in result.output
    assert not env_sqlite.exists()
    assert not env_duckdb.exists()
    assert not xdg_sqlite.exists()
    assert not xdg_duckdb.exists()


def test_ctx_import_does_not_mutate_opencode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    before = hashlib.sha256(source_db.read_bytes()).hexdigest()
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))

    result = CliRunner().invoke(main, ["ctx", "import"])

    assert result.exit_code == 0, result.output
    assert hashlib.sha256(source_db.read_bytes()).hexdigest() == before
    con = sqlite3.connect(source_db)
    try:
        assert con.execute("SELECT 1 FROM sqlite_master WHERE name = 'alembic_version'").fetchone() is None
    finally:
        con.close()


def test_search_uses_imported_index_when_opencode_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "missing-opencode.db"))

    result = runner.invoke(main, ["ctx", "search", "native event marker", "--refresh", "off"])

    assert result.exit_code == 0, result.output
    assert "evt_native_tool" in result.output


def test_refresh_off_does_not_create_missing_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "missing-ctx.sqlite"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))

    result = CliRunner().invoke(main, ["ctx", "search", "native event marker", "--refresh", "off"])

    assert result.exit_code != 0
    assert not ctx_db.exists()
    assert "import" in result.output.lower() or "index" in result.output.lower()


def test_default_import_prunes_rows_missing_from_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    assert _ctx_count(ctx_db, "ctx_event", "event_id = 'evt_native_patch'") == 1
    assert _ctx_count(ctx_db, "ctx_session", "provider_session_id = 's-sub'") == 1

    _delete_source_history_rows(source_db)
    imported_again = runner.invoke(main, ["ctx", "import"])

    assert imported_again.exit_code == 0, imported_again.output
    assert _ctx_count(ctx_db, "ctx_event", "event_id = 'evt_native_patch'") == 0
    assert _ctx_count(ctx_db, "ctx_file_touched", "event_id = 'evt_native_patch'") == 0
    assert _ctx_count(ctx_db, "ctx_event_fts", "event_id = 'evt_native_patch'") == 0
    assert _ctx_count(ctx_db, "ctx_session", "provider_session_id = 's-sub'") == 0
    assert _ctx_count(ctx_db, "ctx_event", "event_id IN ('m-sub', 'p-sub-step', 'evt_sub')") == 0
    assert _ctx_count(ctx_db, "ctx_event", "event_id = 'evt_native_tool'") == 1


def test_default_search_refresh_prunes_rows_missing_from_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    _delete_event(source_db, "evt_native_tool")

    result = runner.invoke(main, ["ctx", "search", "related term error text"])

    assert result.exit_code == 0, result.output
    assert result.output == "No results\n"
    assert _ctx_count(ctx_db, "ctx_event", "event_id = 'evt_native_tool'") == 0


def test_refresh_off_searches_existing_index_without_pruning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    _delete_event(source_db, "evt_native_tool")

    result = runner.invoke(main, ["ctx", "search", "related term error text", "--refresh", "off"])

    assert result.exit_code == 0, result.output
    assert "evt_native_tool" in result.output
    assert _ctx_count(ctx_db, "ctx_event", "event_id = 'evt_native_tool'") == 1


def _ctx_counts(ctx_db: Path) -> dict[str, int]:
    con = sqlite3.connect(ctx_db)
    try:
        return {
            table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ["alembic_version", "ctx_session", "ctx_event", "ctx_file_touched", "ctx_event_fts"]
        }
    finally:
        con.close()


def _ctx_count(ctx_db: Path, table: str, where: str) -> int:
    con = sqlite3.connect(ctx_db)
    try:
        return int(con.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0] or 0)
    finally:
        con.close()


def _delete_source_history_rows(source_db: Path) -> None:
    """Mutate a pytest-owned fixture DB to model source history disappearing between imports."""
    with sqlite3.connect(source_db) as connection:
        connection.execute("DELETE FROM event WHERE id IN ('evt_native_patch', 'evt_sub')")
        connection.execute("DELETE FROM part WHERE id = 'p-sub-step'")
        connection.execute("DELETE FROM session_message WHERE session_id = 's-sub' OR message_id = 'm-sub'")
        connection.execute("DELETE FROM message WHERE id = 'm-sub'")
        connection.execute("DELETE FROM session WHERE id = 's-sub'")


def _delete_event(source_db: Path, event_id: str) -> None:
    with sqlite3.connect(source_db) as connection:
        connection.execute("DELETE FROM event WHERE id = ?", (event_id,))


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
