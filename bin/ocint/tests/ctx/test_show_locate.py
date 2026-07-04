import json

from click.testing import CliRunner

from ocint.cli import main

from tests.fixtures.opencode_db import create_opencode_db


def test_ctx_show_event_uses_native_event_ids(tmp_path, monkeypatch) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(db_path))

    result = CliRunner().invoke(main, ["ctx", "show", "event", "evt_native_tool", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["selected"]["event_id"] == "evt_native_tool"
    assert payload["selected"]["source_table"] == "event"
    assert payload["selected"]["session_id"] == "s-primary"
    assert [event["event_id"] for event in payload["events"]]


def test_ctx_show_session_full_renders_untruncated_event_text(tmp_path, monkeypatch) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(db_path))

    result = CliRunner().invoke(main, ["ctx", "show", "session", "s-primary", "--mode", "full"])

    assert result.exit_code == 0, result.output
    assert "IMPORTANT_LATE_MARKER" in result.output


def test_ctx_show_event_renders_selected_event_untruncated(tmp_path, monkeypatch) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(db_path))

    result = CliRunner().invoke(main, ["ctx", "show", "event", "evt_long_payload", "--window", "0"])

    assert result.exit_code == 0, result.output
    assert "IMPORTANT_LATE_MARKER" in result.output


def test_ctx_show_event_json_includes_full_text_and_snippet(tmp_path, monkeypatch) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(db_path))

    result = CliRunner().invoke(main, ["ctx", "show", "event", "evt_long_payload", "--window", "0", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "IMPORTANT_LATE_MARKER" in payload["selected"]["text"]
    assert "IMPORTANT_LATE_MARKER" not in payload["selected"]["snippet"]


def test_ctx_locate_event_uses_native_event_ids(tmp_path, monkeypatch) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(db_path))

    result = CliRunner().invoke(main, ["ctx", "locate", "event", "evt_native_tool", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["kind"] == "event"
    assert payload["source_table"] == "event"
    assert payload["session_id"] == "s-primary"
    assert payload["citation"] == "opencode session=s-primary event=evt_native_tool table=event"
