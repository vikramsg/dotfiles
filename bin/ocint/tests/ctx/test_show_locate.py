import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from ocint.cli import main
from sqlalchemy import create_engine, text
from tests.fixtures.opencode_db import create_opencode_db


def test_ctx_show_event_uses_native_event_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(main, ["ctx", "show", "event", "evt_native_tool", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["selected"]["event_id"] == "evt_native_tool"
    assert payload["selected"]["source_table"] == "event"
    assert payload["selected"]["session_id"] == "s-primary"
    assert [event["event_id"] for event in payload["events"]]


def test_ctx_show_session_full_renders_untruncated_event_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(main, ["ctx", "show", "session", "s-primary", "--mode", "full"])

    assert result.exit_code == 0, result.output
    assert "IMPORTANT_LATE_MARKER" in result.output


def test_ctx_show_event_renders_selected_event_untruncated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(main, ["ctx", "show", "event", "evt_long_payload", "--window", "0"])

    assert result.exit_code == 0, result.output
    assert "IMPORTANT_LATE_MARKER" in result.output


def test_ctx_show_event_json_includes_full_text_and_snippet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(main, ["ctx", "show", "event", "evt_long_payload", "--window", "0", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "IMPORTANT_LATE_MARKER" in payload["selected"]["text"]
    assert "IMPORTANT_LATE_MARKER" not in payload["selected"]["snippet"]


def test_ctx_locate_event_uses_native_event_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_db = _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(main, ["ctx", "locate", "event", "evt_native_tool", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["kind"] == "event"
    assert payload["source_table"] == "event"
    assert payload["session_id"] == "s-primary"
    assert payload["citation"] == "opencode session=s-primary event=evt_native_tool table=event"
    assert payload["db_path"] == str(source_db)


def test_ctx_locate_session_uses_imported_source_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_db = _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(main, ["ctx", "locate", "session", "s-primary", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["kind"] == "session"
    assert payload["source_table"] == "session"
    assert payload["session_id"] == "s-primary"
    assert payload["db_path"] == str(source_db)


@pytest.mark.parametrize("backend", ["sqlite", "duckdb"])
def test_ctx_show_and_locate_event_work_for_backend(
    backend: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if backend == "duckdb":
        _skip_if_duckdb_fts_unavailable(tmp_path)
    source_db = _import_fixture(tmp_path, monkeypatch, backend=backend)
    runner = CliRunner()

    shown = runner.invoke(main, ["ctx", "--backend", backend, "show", "event", "evt_native_tool", "--json"])
    located = runner.invoke(main, ["ctx", "--backend", backend, "locate", "event", "evt_native_tool", "--json"])

    assert shown.exit_code == 0, shown.output
    assert located.exit_code == 0, located.output
    shown_payload = json.loads(shown.output)
    located_payload = json.loads(located.output)
    assert shown_payload["selected"]["event_id"] == "evt_native_tool"
    assert shown_payload["selected"]["source_table"] == "event"
    assert shown_payload["selected"]["session_id"] == "s-primary"
    assert "native event marker" in shown_payload["selected"]["text"]
    assert located_payload["db_path"] == str(source_db)


def _import_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, backend: str = "sqlite") -> Path:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))
    monkeypatch.setenv("OCINT_CTX_DUCKDB", str(tmp_path / "ctx.duckdb"))
    imported = CliRunner().invoke(main, ["ctx", "--backend", backend, "import"])
    assert imported.exit_code == 0, imported.output
    monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "missing-opencode.db"))
    return source_db


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
