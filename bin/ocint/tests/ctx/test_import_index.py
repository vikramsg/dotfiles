import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner
from ocint.cli import main
from ocint.ctx.db import current_ctx_head_revision
from ocint.ctx.models import CtxImportRequest
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
    assert _ctx_revision(ctx_db) == current_ctx_head_revision()
    assert _ctx_columns(ctx_db, "ctx_source") == [
        "id",
        "provider",
        "source_type",
        "name",
        "source_path",
        "sessions",
        "events",
    ]
    assert "source_fingerprint" in _ctx_columns(ctx_db, "ctx_event")
    assert _ctx_count(ctx_db, "ctx_refresh_state", "latest_attempt_status = 'success'") == 1
    assert counts_after_first["ctx_event_fts"] > 0
    assert counts_after_first["ctx_session"] == 2
    assert counts_after_first["ctx_event"] > 0
    assert counts_after_first["ctx_file_touched"] > 0


def test_ctx_import_only_indexes_message_and_part_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    runner = CliRunner()

    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "missing-opencode.db"))

    con = sqlite3.connect(ctx_db)
    try:
        source_tables = {
            row[0] for row in con.execute("SELECT DISTINCT source_table FROM ctx_event ORDER BY source_table")
        }
        raw_markers = con.execute(
            """
            SELECT COUNT(*)
            FROM ctx_event
            WHERE full_text LIKE '%RAW_EVENT_ONLY_MARKER%'
               OR search_text LIKE '%RAW_EVENT_ONLY_MARKER%'
            """
        ).fetchone()[0]
    finally:
        con.close()
    assert source_tables == {"message", "part"}
    assert raw_markers == 0

    result = runner.invoke(main, ["ctx", "search", "RAW_EVENT_ONLY_MARKER", "--refresh", "off"])

    assert result.exit_code == 0, result.output
    assert result.output == "No results\n"


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


def test_ctx_import_rejects_ctx_db_alias_to_opencode_without_mutating_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    before_hash = hashlib.sha256(source_db.read_bytes()).hexdigest()
    before_journal_mode = _sqlite_journal_mode(source_db)
    before_schema = _sqlite_schema(source_db)
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(source_db))

    result = CliRunner().invoke(main, ["ctx", "import"])

    assert result.exit_code != 0
    assert "same file" in result.output
    assert hashlib.sha256(source_db.read_bytes()).hexdigest() == before_hash
    assert _sqlite_journal_mode(source_db) == before_journal_mode
    assert _sqlite_schema(source_db) == before_schema
    con = sqlite3.connect(source_db)
    try:
        assert con.execute("SELECT 1 FROM sqlite_master WHERE name = 'alembic_version'").fetchone() is None
    finally:
        con.close()


def test_default_search_rejects_ctx_db_alias_to_opencode_without_mutating_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    before_hash = hashlib.sha256(source_db.read_bytes()).hexdigest()
    before_journal_mode = _sqlite_journal_mode(source_db)
    before_schema = _sqlite_schema(source_db)
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(source_db))

    result = CliRunner().invoke(main, ["ctx", "search", "native event marker"])

    assert result.exit_code != 0
    assert "same file" in result.output
    assert hashlib.sha256(source_db.read_bytes()).hexdigest() == before_hash
    assert _sqlite_journal_mode(source_db) == before_journal_mode
    assert _sqlite_schema(source_db) == before_schema
    con = sqlite3.connect(source_db)
    try:
        assert con.execute("SELECT 1 FROM sqlite_master WHERE name = 'alembic_version'").fetchone() is None
        assert con.execute("SELECT 1 FROM sqlite_master WHERE name = 'ctx_refresh_state'").fetchone() is None
    finally:
        con.close()


def test_ctx_db_symlink_to_source_rejected_without_mutating_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_link = tmp_path / "ctx-link.sqlite"
    ctx_link.symlink_to(source_db)
    before_hash = hashlib.sha256(source_db.read_bytes()).hexdigest()
    before_journal_mode = _sqlite_journal_mode(source_db)
    before_schema = _sqlite_schema(source_db)
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_link))

    result = CliRunner().invoke(main, ["ctx", "import"])

    assert result.exit_code != 0
    assert "same file" in result.output
    assert hashlib.sha256(source_db.read_bytes()).hexdigest() == before_hash
    assert _sqlite_journal_mode(source_db) == before_journal_mode
    assert _sqlite_schema(source_db) == before_schema


@pytest.mark.parametrize(
    "command",
    [
        ["ctx", "status"],
        ["ctx", "sources"],
        ["ctx", "search", "native event marker", "--refresh", "off"],
        ["ctx", "show", "session"],
        ["ctx", "show", "event", "p-primary-step"],
        ["ctx", "locate", "session", "s-primary"],
        ["ctx", "locate", "event", "p-primary-step"],
        ["ctx", "sql", "SELECT provider FROM ctx_sources"],
    ],
)
def test_read_only_ctx_commands_reject_ctx_db_alias_before_opening_source(
    command: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    before_hash = hashlib.sha256(source_db.read_bytes()).hexdigest()
    before_journal_mode = _sqlite_journal_mode(source_db)
    before_schema = _sqlite_schema(source_db)
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(source_db))

    result = CliRunner().invoke(main, command)

    assert result.exit_code != 0
    assert "same file" in result.output
    assert hashlib.sha256(source_db.read_bytes()).hexdigest() == before_hash
    assert _sqlite_journal_mode(source_db) == before_journal_mode
    assert _sqlite_schema(source_db) == before_schema


def test_ctx_import_help_removes_full_rebuild_flag() -> None:
    result = CliRunner().invoke(main, ["ctx", "import", "--help"])

    assert result.exit_code == 0, result.output
    assert "--source-db" in result.output
    assert "--json" in result.output
    assert "--full" not in result.output
    assert "full" not in CtxImportRequest.model_fields


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
    assert "p-primary-step" in result.output


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
    assert _ctx_count(ctx_db, "ctx_event", "event_id = 'p-primary-patch'") == 1
    assert _ctx_count(ctx_db, "ctx_session", "provider_session_id = 's-sub'") == 1

    _delete_source_history_rows(source_db)
    imported_again = runner.invoke(main, ["ctx", "import"])

    assert imported_again.exit_code == 0, imported_again.output
    assert _ctx_count(ctx_db, "ctx_event", "event_id = 'p-primary-patch'") == 0
    assert _ctx_count(ctx_db, "ctx_file_touched", "event_id = 'p-primary-patch'") == 0
    assert _ctx_count(ctx_db, "ctx_event_fts", "event_id = 'p-primary-patch'") == 0
    assert _ctx_count(ctx_db, "ctx_session", "provider_session_id = 's-sub'") == 0
    assert _ctx_count(ctx_db, "ctx_event", "event_id IN ('m-sub', 'p-sub-step')") == 0
    assert _ctx_count(ctx_db, "ctx_event", "event_id = 'p-primary-step'") == 1


def test_default_search_refresh_prunes_rows_missing_from_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    monkeypatch.setenv("OCINT_CTX_REFRESH_TTL", "0")
    scheduled: list[tuple[Path, Path, Path]] = []
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    _delete_part(source_db, "p-primary-step")

    def record_schedule(*, ctx_db_path: Path, source_db_path: Path, log_path: Path) -> int:
        scheduled.append((ctx_db_path, source_db_path, log_path))
        return 101

    monkeypatch.setattr("ocint.ctx.cli.schedule_refresh_worker", record_schedule)

    result = runner.invoke(main, ["ctx", "search", "related term error text"])

    assert result.exit_code == 0, result.output
    assert "p-primary-step" in result.output
    assert _ctx_count(ctx_db, "ctx_event", "event_id = 'p-primary-step'") == 1
    assert scheduled == [(ctx_db, source_db, ctx_db.parent / "ctx.sqlite.refresh.log")]


def test_refresh_off_searches_existing_index_without_pruning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    _delete_part(source_db, "p-primary-step")

    result = runner.invoke(main, ["ctx", "search", "related term error text", "--refresh", "off"])

    assert result.exit_code == 0, result.output
    assert "p-primary-step" in result.output
    assert _ctx_count(ctx_db, "ctx_event", "event_id = 'p-primary-step'") == 1


def test_incremental_refresh_updates_changed_event_without_replacing_primary_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    event_pk = _ctx_scalar(ctx_db, "SELECT id FROM ctx_event WHERE event_id = 'p-primary-step'")
    untouched_event_pk = _ctx_scalar(ctx_db, "SELECT id FROM ctx_event WHERE event_id = 'p-primary-patch'")

    _update_part_payload(
        source_db,
        "p-primary-step",
        {
            "type": "step-finish",
            "path": "docs/incremental-refresh.md",
            "text": "replacement incremental marker",
        },
    )
    refreshed = runner.invoke(main, ["ctx", "import"])

    assert refreshed.exit_code == 0, refreshed.output
    assert _ctx_scalar(ctx_db, "SELECT id FROM ctx_event WHERE event_id = 'p-primary-step'") == event_pk
    assert _ctx_scalar(ctx_db, "SELECT id FROM ctx_event WHERE event_id = 'p-primary-patch'") == untouched_event_pk
    new_result = runner.invoke(main, ["ctx", "search", "replacement incremental marker", "--refresh", "off"])
    old_result = runner.invoke(main, ["ctx", "search", "related term error text", "--refresh", "off"])
    assert new_result.exit_code == 0, new_result.output
    assert "p-primary-step" in new_result.output
    assert old_result.exit_code == 0, old_result.output
    assert old_result.output == "No results\n"
    assert _ctx_file_paths(ctx_db, "p-primary-step") == ["docs/incremental-refresh.md"]


def test_incremental_refresh_reprojects_events_when_source_session_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    deleted_title = "VanishedSessionTitleAlpha"
    deleted_workspace = "/tmp/VanishedWorkspaceBeta"
    _update_session_identity_terms(source_db, session_id="s-sub", title=deleted_title, workspace=deleted_workspace)
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    event_pk = _ctx_scalar(ctx_db, "SELECT id FROM ctx_event WHERE event_id = 'p-sub-step'")
    assert _ctx_count(ctx_db, "ctx_event", f"event_id = 'p-sub-step' AND search_text LIKE '%{deleted_title}%'") == 1

    _delete_session_only(source_db, "s-sub")
    refreshed = runner.invoke(main, ["ctx", "import"])

    assert refreshed.exit_code == 0, refreshed.output
    assert _ctx_count(ctx_db, "ctx_session", "provider_session_id = 's-sub'") == 0
    assert _ctx_count(ctx_db, "ctx_event", "event_id = 'p-sub-step'") == 1
    assert _ctx_scalar(ctx_db, "SELECT id FROM ctx_event WHERE event_id = 'p-sub-step'") == event_pk
    assert (
        _ctx_count(ctx_db, "ctx_event", f"provider_session_id = 's-sub' AND search_text LIKE '%{deleted_title}%'") == 0
    )
    assert (
        _ctx_count(ctx_db, "ctx_event", f"provider_session_id = 's-sub' AND search_text LIKE '%{deleted_workspace}%'")
        == 0
    )
    assert _ctx_fts_match_count(ctx_db, deleted_title) == 0
    search = runner.invoke(main, ["ctx", "search", deleted_title, "--refresh", "off"])
    assert search.exit_code == 0, search.output
    assert search.output == "No results\n"


def _ctx_counts(ctx_db: Path) -> dict[str, int]:
    con = sqlite3.connect(ctx_db)
    try:
        return {
            table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ["alembic_version", "ctx_session", "ctx_event", "ctx_file_touched", "ctx_event_fts"]
        }
    finally:
        con.close()


def _ctx_revision(ctx_db: Path) -> str:
    con = sqlite3.connect(ctx_db)
    try:
        return str(con.execute("SELECT version_num FROM alembic_version").fetchone()[0])
    finally:
        con.close()


def _ctx_columns(ctx_db: Path, table: str) -> list[str]:
    con = sqlite3.connect(ctx_db)
    try:
        return [str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")]
    finally:
        con.close()


def _sqlite_schema(path: Path) -> list[tuple[str, str, str | None]]:
    con = sqlite3.connect(path)
    try:
        return list(
            con.execute(
                """
                SELECT type, name, sql
                FROM sqlite_master
                ORDER BY type, name
                """
            )
        )
    finally:
        con.close()


def _sqlite_journal_mode(path: Path) -> str:
    con = sqlite3.connect(path)
    try:
        return str(con.execute("PRAGMA journal_mode").fetchone()[0])
    finally:
        con.close()


def _ctx_count(ctx_db: Path, table: str, where: str) -> int:
    con = sqlite3.connect(ctx_db)
    try:
        return int(con.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0] or 0)
    finally:
        con.close()


def _ctx_scalar(ctx_db: Path, sql: str) -> object:
    con = sqlite3.connect(ctx_db)
    try:
        return con.execute(sql).fetchone()[0]
    finally:
        con.close()


def _ctx_file_paths(ctx_db: Path, event_id: str) -> list[str]:
    con = sqlite3.connect(ctx_db)
    try:
        return [
            str(row[0])
            for row in con.execute(
                "SELECT path FROM ctx_file_touched WHERE event_id = ? ORDER BY path",
                (event_id,),
            )
        ]
    finally:
        con.close()


def _ctx_fts_match_count(ctx_db: Path, query: str) -> int:
    con = sqlite3.connect(ctx_db)
    try:
        return int(
            con.execute("SELECT COUNT(*) FROM ctx_event_fts WHERE ctx_event_fts MATCH ?", (query,)).fetchone()[0] or 0
        )
    finally:
        con.close()


def _delete_source_history_rows(source_db: Path) -> None:
    """Mutate a pytest-owned fixture DB to model source history disappearing between imports."""
    with sqlite3.connect(source_db) as connection:
        connection.execute("DELETE FROM part WHERE id IN ('p-primary-patch', 'p-sub-step')")
        connection.execute("DELETE FROM session_message WHERE session_id = 's-sub' OR message_id = 'm-sub'")
        connection.execute("DELETE FROM message WHERE id = 'm-sub'")
        connection.execute("DELETE FROM session WHERE id = 's-sub'")


def _delete_part(source_db: Path, event_id: str) -> None:
    with sqlite3.connect(source_db) as connection:
        connection.execute("DELETE FROM part WHERE id = ?", (event_id,))


def _delete_session_only(source_db: Path, session_id: str) -> None:
    with sqlite3.connect(source_db) as connection:
        connection.execute("DELETE FROM session WHERE id = ?", (session_id,))


def _update_part_payload(source_db: Path, event_id: str, payload: dict[str, object]) -> None:
    with sqlite3.connect(source_db) as connection:
        connection.execute(
            "UPDATE part SET data = ?, timeUpdated = timeUpdated + 1 WHERE id = ?",
            (json.dumps(payload), event_id),
        )


def _update_session_identity_terms(source_db: Path, *, session_id: str, title: str, workspace: str) -> None:
    with sqlite3.connect(source_db) as connection:
        connection.execute(
            "UPDATE session SET title = ?, directory = ?, data = ? WHERE id = ?",
            (title, workspace, json.dumps({"title": title, "directory": workspace}), session_id),
        )
