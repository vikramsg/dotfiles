import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from ocint.cli import main
from tests.support.opencode_db import create_opencode_db


def test_ctx_show_event_uses_normalized_message_part_event_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(main, ["ctx", "show", "event", "p-primary-step", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["selected"]["event_id"] == "p-primary-step"
    assert payload["selected"]["source_table"] == "part"
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

    result = CliRunner().invoke(main, ["ctx", "show", "event", "p-long-payload", "--window", "0"])

    assert result.exit_code == 0, result.output
    assert "IMPORTANT_LATE_MARKER" in result.output


def test_ctx_show_event_json_includes_full_text_and_snippet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(main, ["ctx", "show", "event", "p-long-payload", "--window", "0", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "IMPORTANT_LATE_MARKER" in payload["selected"]["text"]
    assert "IMPORTANT_LATE_MARKER" not in payload["selected"]["snippet"]


def test_ctx_locate_event_uses_normalized_message_part_event_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_db = _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(main, ["ctx", "locate", "event", "p-primary-step", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["kind"] == "event"
    assert payload["source_table"] == "part"
    assert payload["session_id"] == "s-primary"
    assert payload["citation"] == "opencode session=s-primary event=p-primary-step table=part"
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


def _import_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))
    imported = CliRunner().invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "missing-opencode.db"))
    return source_db
