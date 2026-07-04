import hashlib
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner
from ocint.cli import main
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
