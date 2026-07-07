import json
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path

import pytest
from click.testing import CliRunner
from ocint._models import CliContext, CliProgress
from ocint.cli import main
from ocint.ctx.config import resolve_ctx_refresh_config
from ocint.ctx.refresh import acquire_refresh_lock
from tests.fixtures.opencode_db import create_opencode_db


def test_search_auto_imports_when_index_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))

    result = CliRunner().invoke(main, ["ctx", "search", "native event marker"])

    assert result.exit_code == 0, result.output
    assert "p-primary-step" in result.output
    assert ctx_db.exists()


def test_search_auto_import_reports_progress_through_injected_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    output = RecordingOutput()
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))

    result = CliRunner().invoke(
        main,
        ["ctx", "search", "native event marker", "--limit", "1"],
        obj=CliContext(output=output),
    )

    assert result.exit_code == 0, result.output
    assert output.progress_starts == ["Importing OpenCode history into ocint ctx index"]
    assert "Loading sessions" in output.progress_messages
    assert "Loading events" in output.progress_messages
    assert "Writing events" in output.progress_messages
    assert any("session=s-primary" in write.text for write in output.writes)


def test_search_json_disables_import_progress_and_keeps_output_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    output = RecordingOutput()
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))

    result = CliRunner().invoke(
        main,
        ["ctx", "search", "native event marker", "--limit", "1", "--json"],
        obj=CliContext(output=output),
    )

    assert result.exit_code == 0, result.output
    assert output.progress_starts == []
    payload = json.loads(output.writes[0].text)
    assert payload[0]["event_id"]


def test_import_command_reports_progress_for_human_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    output = RecordingOutput()
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))

    result = CliRunner().invoke(main, ["ctx", "import"], obj=CliContext(output=output))

    assert result.exit_code == 0, result.output
    assert output.progress_starts == ["Importing OpenCode history into ocint ctx index"]
    assert "Writing events" in output.progress_messages
    assert any("SESSIONS_SEEN" in write.text for write in output.writes)


def test_import_json_disables_progress_and_keeps_output_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    output = RecordingOutput()
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))

    result = CliRunner().invoke(main, ["ctx", "import", "--json"], obj=CliContext(output=output))

    assert result.exit_code == 0, result.output
    assert output.progress_starts == []
    payload = json.loads(output.writes[0].text)
    assert payload["sessions_seen"] == 2


def test_refresh_off_does_not_auto_import_and_guides_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    output = RecordingOutput()
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))

    result = CliRunner().invoke(
        main,
        ["ctx", "search", "native event marker", "--refresh", "off"],
        obj=CliContext(output=output),
    )

    assert result.exit_code != 0
    assert output.progress_starts == []
    assert "run `ocint ctx import` first" in result.output
    assert 'ocint ctx search "native event marker"' in result.output
    assert "without `--refresh off`" in result.output


def test_show_session_without_id_lists_recent_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(main, ["ctx", "show", "session"])

    assert result.exit_code == 0, result.output
    assert "Recent sessions" in result.output
    assert "s-primary" in result.output
    assert "ocint ctx show session " in result.output
    assert 'ocint ctx search "what you remember"' in result.output


def test_show_session_without_id_works_after_source_db_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "missing-opencode.db"))

    result = CliRunner().invoke(main, ["ctx", "show", "session"])

    assert result.exit_code == 0, result.output
    assert "Recent sessions" in result.output
    assert "s-primary" in result.output


def test_show_session_with_id_still_renders_transcript(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(main, ["ctx", "show", "session", "s-primary"])

    assert result.exit_code == 0, result.output
    assert "SESSION: s-primary" in result.output


def test_docs_show_without_topic_lists_topics() -> None:
    result = CliRunner().invoke(main, ["ctx", "docs", "show"])

    assert result.exit_code == 0, result.output
    assert "Available topics" in result.output
    for topic in ["quickstart", "commands", "discovery", "refresh", "sql"]:
        assert topic in result.output
    assert "ocint ctx docs show quickstart" in result.output


def test_docs_show_topic_still_renders_topic() -> None:
    result = CliRunner().invoke(main, ["ctx", "docs", "show", "sql"])

    assert result.exit_code == 0, result.output
    assert "ctx_sessions" in result.output


def test_docs_show_help_explains_optional_topic() -> None:
    result = CliRunner().invoke(main, ["ctx", "docs", "show", "--help"])

    assert result.exit_code == 0
    assert "[TOPIC]" in result.output
    assert "quickstart" in result.output
    assert "ocint ctx docs show" in result.output


def test_ctx_help_has_first_use_flow() -> None:
    result = CliRunner().invoke(main, ["ctx", "--help"])

    assert result.exit_code == 0
    assert 'ocint ctx search "what you remember"' in result.output
    assert "ocint ctx show session" in result.output


def test_search_help_explains_auto_refresh_without_now() -> None:
    result = CliRunner().invoke(main, ["ctx", "search", "--help"])

    assert result.exit_code == 0
    assert "Default search uses auto refresh" in result.output
    assert "stale" in result.output
    assert "--refresh off" in result.output
    assert "index-only" in result.output
    assert "now" not in result.output


def test_search_rejects_refresh_now(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))

    result = CliRunner().invoke(main, ["ctx", "search", "native event marker", "--refresh", "now"])

    assert result.exit_code != 0
    assert "Invalid value for '--refresh'" in result.output
    assert not (tmp_path / "ctx.sqlite").exists()


def test_refresh_off_bypasses_invalid_ttl_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))
    monkeypatch.setenv("OCINT_CTX_REFRESH_TTL", "invalid")

    result = CliRunner().invoke(main, ["ctx", "search", "native event marker", "--refresh", "off"])

    assert result.exit_code != 0
    assert "OCINT_CTX_REFRESH_TTL" not in result.output
    assert not (tmp_path / "ctx.sqlite").exists()


def test_stale_ready_search_schedules_background_refresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    scheduled: list[tuple[Path, Path, Path]] = []
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    monkeypatch.setenv("OCINT_CTX_REFRESH_TTL", "0")
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output

    def record_schedule(*, ctx_db_path: Path, source_db_path: Path, log_path: Path) -> int:
        scheduled.append((ctx_db_path, source_db_path, log_path))
        return 4242

    monkeypatch.setattr("ocint.ctx.cli.schedule_refresh_worker", record_schedule)

    result = runner.invoke(main, ["ctx", "search", "native event marker", "--limit", "1", "--verbose"])

    assert result.exit_code == 0, result.output
    assert "p-primary-step" in result.output
    assert "ctx refresh scheduled" in result.output
    assert scheduled == [(ctx_db, source_db, ctx_db.parent / "ctx.sqlite.refresh.log")]


def test_hidden_refresh_worker_exits_successfully_when_lock_is_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    refresh_config = resolve_ctx_refresh_config(ctx_db_path=ctx_db, env={})

    with acquire_refresh_lock(refresh_config.lock_path, blocking=False) as lock:
        assert lock.acquired
        result = runner.invoke(main, ["ctx", "refresh-worker"])

    assert result.exit_code == 0, result.output
    assert "refresh-worker" not in runner.invoke(main, ["ctx", "--help"]).output


def test_show_session_help_explains_no_id_behavior() -> None:
    result = CliRunner().invoke(main, ["ctx", "show", "session", "--help"])

    assert result.exit_code == 0
    assert "[SESSION_ID]" in result.output
    assert "Without SESSION_ID" in result.output
    assert "ocint ctx show session <session-id>" in result.output


class RecordedWrite:
    def __init__(self, text: str, *, stderr: bool, nl: bool) -> None:
        self.text = text
        self.stderr = stderr
        self.nl = nl


class RecordingProgress:
    def __init__(self, output: RecordingOutput) -> None:
        self._output = output

    def update(self, message: str, *, current: int | None = None, total: int | None = None) -> None:
        self._output.progress_events.append((message, current, total))


class RecordingOutput:
    def __init__(self) -> None:
        self.writes: list[RecordedWrite] = []
        self.progress_starts: list[str] = []
        self.progress_events: list[tuple[str, int | None, int | None]] = []

    @property
    def progress_messages(self) -> set[str]:
        return {message for message, _current, _total in self.progress_events}

    def write(self, text: str, *, stderr: bool = False, nl: bool = False, enabled: bool = True) -> None:
        if enabled:
            self.writes.append(RecordedWrite(text, stderr=stderr, nl=nl))

    def progress(self, message: str, *, enabled: bool = True) -> AbstractContextManager[CliProgress]:
        if not enabled:
            return nullcontext(RecordingProgress(self))
        self.progress_starts.append(message)
        return nullcontext(RecordingProgress(self))


def _import_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))
    imported = CliRunner().invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
