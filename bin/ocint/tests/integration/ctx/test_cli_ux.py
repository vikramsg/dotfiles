import json
import sqlite3
import threading
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from ocint._models import CliContext, CliProgress
from ocint.cli import main
from ocint.ctx.config import resolve_ctx_refresh_config
from ocint.ctx.refresh import acquire_refresh_lock
from ocint.opencode.repository import OpenCodeRepository
from tests.support.opencode_db import create_opencode_db


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
    assert any("importing before search" in write.text and write.stderr for write in output.writes)
    assert "Loading sessions" in output.progress_messages
    assert "Loading events" in output.progress_messages
    assert "Writing events" in output.progress_messages
    assert len(output.displays) == 1


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
    assert output.displays == []


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


@pytest.mark.parametrize("alias_kind", ["symlink", "dotdot"])
def test_default_search_reuses_fresh_index_for_canonical_source_alias(
    alias_kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_db = create_opencode_db(source_dir / "opencode.db")
    alias_path = _source_alias_path(source_db, alias_kind=alias_kind)
    ctx_db = tmp_path / "ctx" / "ctx.sqlite"
    output = RecordingOutput()
    scheduled: list[tuple[Path, Path, Path]] = []
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    monkeypatch.setenv("OPENCODE_DB", str(alias_path))
    monkeypatch.setattr(
        "ocint.ctx.cli.schedule_refresh_worker",
        lambda *, ctx_db_path, source_db_path, log_path: (
            scheduled.append((ctx_db_path, source_db_path, log_path)) or 42
        ),
    )

    result = runner.invoke(
        main,
        ["ctx", "search", "native event marker", "--limit", "1"],
        obj=CliContext(output=output),
    )

    assert result.exit_code == 0, result.output
    assert len(output.displays) == 1
    assert output.progress_starts == []
    assert scheduled == []
    assert _ctx_source_paths(ctx_db) == [str(source_db.resolve(strict=False))]


def test_stale_search_schedules_worker_with_canonical_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_db = create_opencode_db(source_dir / "opencode.db")
    source_alias = _source_alias_path(source_db, alias_kind="symlink")
    ctx_db = tmp_path / "ctx" / "../ctx.sqlite"
    canonical_ctx_db = ctx_db.resolve(strict=False)
    scheduled: list[tuple[Path, Path, Path]] = []
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    monkeypatch.setenv("OPENCODE_DB", str(source_alias))
    monkeypatch.setenv("OCINT_CTX_REFRESH_TTL", "0")

    def record_schedule(*, ctx_db_path: Path, source_db_path: Path, log_path: Path) -> int:
        scheduled.append((ctx_db_path, source_db_path, log_path))
        return 4243

    monkeypatch.setattr("ocint.ctx.cli.schedule_refresh_worker", record_schedule)

    result = runner.invoke(main, ["ctx", "search", "native event marker", "--limit", "1"])

    assert result.exit_code == 0, result.output
    assert "p-primary-step" in result.output
    assert scheduled == [
        (
            canonical_ctx_db,
            source_db.resolve(strict=False),
            canonical_ctx_db.parent / f"{canonical_ctx_db.name}.refresh.log",
        )
    ]


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
        result = runner.invoke(main, ["ctx", "refresh-worker", "--run-id", "held-lock-run"])

    assert result.exit_code == 0, result.output
    assert "refresh-worker" not in runner.invoke(main, ["ctx", "--help"]).output


def test_foreground_refresh_startup_acquires_lock_before_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    refresh_config = resolve_ctx_refresh_config(ctx_db_path=ctx_db, env={})
    migrate_calls: list[Path] = []
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    monkeypatch.setattr("ocint.ctx.refresh.run.migrate_ctx_db", lambda path: migrate_calls.append(path))

    with acquire_refresh_lock(refresh_config.lock_path, blocking=False) as lock:
        assert lock.acquired
        result = CliRunner().invoke(main, ["ctx", "import"])

    assert result.exit_code != 0
    assert "already running" in result.output
    assert migrate_calls == []


def test_hidden_refresh_worker_startup_acquires_lock_before_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    refresh_config = resolve_ctx_refresh_config(ctx_db_path=ctx_db, env={})
    migrate_calls: list[Path] = []
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    monkeypatch.setattr("ocint.ctx.refresh.run.migrate_ctx_db", lambda path: migrate_calls.append(path))

    with acquire_refresh_lock(refresh_config.lock_path, blocking=False) as lock:
        assert lock.acquired
        result = CliRunner().invoke(main, ["ctx", "refresh-worker", "--run-id", "startup-lock-run"])

    assert result.exit_code == 0, result.output
    assert result.output == ""
    assert migrate_calls == []


def test_first_refresh_startup_holds_lock_while_migration_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    refresh_config = resolve_ctx_refresh_config(ctx_db_path=ctx_db, env={})
    observed_probe_acquired: list[bool] = []
    from ocint.ctx.refresh import run as refresh_run

    real_migrate = refresh_run.migrate_ctx_db

    def assert_locked_during_migration(path: Path) -> None:
        with acquire_refresh_lock(refresh_config.lock_path, blocking=False) as probe:
            observed_probe_acquired.append(probe.acquired)
        real_migrate(path)

    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    monkeypatch.setattr("ocint.ctx.refresh.run.migrate_ctx_db", assert_locked_during_migration)

    result = CliRunner().invoke(main, ["ctx", "import"])

    assert result.exit_code == 0, result.output
    assert observed_probe_acquired == [False]


def test_status_reports_running_attempt_while_import_work_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    previous_status = json.loads(runner.invoke(main, ["ctx", "status", "--json"]).output)
    blocking_source = BlockingOpenCodeRepository(source_db)
    monkeypatch.setattr("ocint.ctx.refresh.run.OpenCodeRepository", lambda _path: blocking_source)
    import_result: list[Result] = []

    def run_import() -> None:
        import_result.append(CliRunner().invoke(main, ["ctx", "import"]))

    thread = threading.Thread(target=run_import)
    thread.start()
    assert blocking_source.entered.wait(timeout=5), "import did not reach the blocked source read"

    status = runner.invoke(main, ["ctx", "status", "--json"])
    human_status = runner.invoke(main, ["ctx", "status"])

    blocking_source.release.set()
    thread.join(timeout=10)
    assert not thread.is_alive(), "blocked import did not finish after release"
    result = import_result[0]
    assert result.exit_code == 0, result.output
    assert status.exit_code == 0, status.output
    payload = json.loads(status.output)
    assert payload["refresh_in_progress"] is True
    assert payload["latest_attempt_status"] == "running"
    assert payload["latest_attempt_started_at"] is not None
    assert payload["latest_attempt_completed_at"] is None
    assert payload["latest_success_completed_at"] == previous_status["latest_success_completed_at"]
    assert human_status.exit_code == 0, human_status.output
    assert "Refresh: running" in " ".join(human_status.output.split())


def test_hidden_refresh_worker_skips_import_when_post_lock_recheck_is_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    monkeypatch.setenv("OCINT_CTX_REFRESH_TTL", "1h")
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    _insert_worker_skip_source_part(source_db)

    worker = runner.invoke(main, ["ctx", "refresh-worker", "--run-id", "fresh-skip-run"])
    search = runner.invoke(main, ["ctx", "search", "post lock worker skip marker", "--refresh", "off"])

    assert worker.exit_code == 0, worker.output
    assert worker.output == ""
    assert search.exit_code == 0, search.output
    assert search.output == "No results\n"


def test_default_search_refreshes_current_source_when_existing_index_belongs_to_another_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_a = create_opencode_db(tmp_path / "source-a.db")
    source_b = create_opencode_db(tmp_path / "source-b.db")
    ctx_db = tmp_path / "ctx.sqlite"
    source_b_marker = "source b exclusive refresh marker"
    _update_source_b_marker(source_b, source_b_marker)
    monkeypatch.setenv("OPENCODE_DB", str(source_a))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    monkeypatch.setenv("OPENCODE_DB", str(source_b))

    result = runner.invoke(main, ["ctx", "search", source_b_marker])

    assert result.exit_code == 0, result.output
    assert "p-primary-step" in result.output
    assert source_b_marker in result.output


def test_failed_refresh_preserves_success_state_and_attempt_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    previous_status = json.loads(runner.invoke(main, ["ctx", "status", "--json"]).output)
    previous_success = previous_status["latest_success_completed_at"]
    assert isinstance(previous_success, int)
    attempt_started_at = previous_success + 1_000
    attempt_completed_at = attempt_started_at + 500
    now_values = iter([attempt_started_at, attempt_completed_at])
    monkeypatch.setattr("ocint.ctx.refresh.run._now_ms", lambda: next(now_values, attempt_completed_at + 1_000))
    monkeypatch.setattr("ocint.ctx.refresh.run.OpenCodeRepository", lambda _path: FailingOpenCodeRepository())

    failed = runner.invoke(main, ["ctx", "import"])
    status = runner.invoke(main, ["ctx", "status", "--json"])
    human_status = runner.invoke(main, ["ctx", "status"])

    assert failed.exit_code != 0
    assert "simulated source failure" in failed.output
    assert status.exit_code == 0, status.output
    payload = json.loads(status.output)
    assert payload["latest_attempt_status"] == "failed"
    assert payload["latest_attempt_started_at"] == attempt_started_at
    assert payload["latest_attempt_completed_at"] == attempt_completed_at
    assert payload["latest_failed_at"] == attempt_completed_at
    assert payload["latest_success_completed_at"] == previous_status["latest_success_completed_at"]
    assert payload["checkpoint_summary"] == previous_status["checkpoint_summary"]
    assert human_status.exit_code == 0, human_status.output
    assert "Refresh: failed" in " ".join(human_status.output.split())
    assert "simulated source failure" in human_status.output


def test_interrupted_foreground_refresh_reports_clean_error_and_records_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    attempt_started_at = 1_783_430_101_000
    attempt_completed_at = attempt_started_at + 500
    now_values = iter([attempt_started_at, attempt_completed_at])
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    monkeypatch.setattr("ocint.ctx.refresh.run._now_ms", lambda: next(now_values, attempt_completed_at + 1_000))
    monkeypatch.setattr("ocint.ctx.refresh.run.OpenCodeRepository", lambda _path: InterruptingOpenCodeRepository())
    runner = CliRunner()

    interrupted = runner.invoke(main, ["ctx", "import"])
    status = runner.invoke(main, ["ctx", "status", "--json"])

    assert interrupted.exit_code != 0
    assert "ctx refresh interrupted" in interrupted.output
    assert "Can't reconnect until invalid transaction is rolled back" not in interrupted.output
    assert status.exit_code == 0, status.output
    payload = json.loads(status.output)
    assert payload["latest_attempt_status"] == "failed"
    assert payload["latest_attempt_started_at"] == attempt_started_at
    assert payload["latest_attempt_completed_at"] == attempt_completed_at
    assert payload["latest_failed_at"] == attempt_completed_at
    assert payload["latest_error_message"] == "KeyboardInterrupt"


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
        self.displays: list[tuple[object, bool]] = []
        self.progress_starts: list[str] = []
        self.progress_events: list[tuple[str, int | None, int | None]] = []

    @property
    def progress_messages(self) -> set[str]:
        return {message for message, _current, _total in self.progress_events}

    def write(self, text: str, *, stderr: bool = False, nl: bool = False, enabled: bool = True) -> None:
        if enabled:
            self.writes.append(RecordedWrite(text, stderr=stderr, nl=nl))

    def display(self, renderable: object, *, stderr: bool = False, enabled: bool = True) -> None:
        if enabled:
            self.displays.append((renderable, stderr))

    def progress(self, message: str, *, enabled: bool = True) -> AbstractContextManager[CliProgress]:
        if not enabled:
            return nullcontext(RecordingProgress(self))
        self.progress_starts.append(message)
        return nullcontext(RecordingProgress(self))


class BlockingOpenCodeRepository:
    def __init__(self, db_path: Path) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self._delegate = OpenCodeRepository(db_path)

    def session_keys(self) -> object:
        self.entered.set()
        if not self.release.wait(timeout=10):
            raise TimeoutError("blocked test source was not released")
        return self._delegate.session_keys()

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)


class FailingOpenCodeRepository:
    def session_keys(self) -> object:
        raise sqlite3.OperationalError("simulated source failure")


class InterruptingOpenCodeRepository:
    def session_keys(self) -> object:
        raise KeyboardInterrupt()


def _source_alias_path(source_db: Path, *, alias_kind: str) -> Path:
    match alias_kind:
        case "symlink":
            link = source_db.parent.parent / f"{source_db.stem}-link{source_db.suffix}"
            link.symlink_to(source_db)
            return link
        case "dotdot":
            nested = source_db.parent / "nested"
            nested.mkdir()
            return nested / ".." / source_db.name
        case _:
            raise ValueError(f"unsupported source alias kind: {alias_kind}")


def _ctx_source_paths(ctx_db: Path) -> list[str]:
    with sqlite3.connect(ctx_db.resolve(strict=False)) as connection:
        return [str(row[0]) for row in connection.execute("SELECT source_path FROM ctx_source ORDER BY source_path")]


def _output_text(output: RecordingOutput) -> str:
    return "".join(write.text for write in output.writes)


def _import_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))
    imported = CliRunner().invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output


def _insert_worker_skip_source_part(source_db: Path) -> None:
    with sqlite3.connect(source_db) as connection:
        timestamp = int(connection.execute("SELECT MAX(timeCreated) + 1 FROM part").fetchone()[0] or 1)
        connection.execute(
            "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
            (
                "p-worker-fresh-skip",
                "m-primary",
                "s-primary",
                timestamp,
                timestamp,
                json.dumps({"type": "text", "text": "post lock worker skip marker"}),
            ),
        )


def _update_source_b_marker(source_db: Path, marker: str) -> None:
    with sqlite3.connect(source_db) as connection:
        connection.execute(
            """
            UPDATE part
            SET data = json_set(data, '$.text', ?), timeUpdated = timeUpdated + 1
            WHERE id = 'p-primary-step'
            """,
            (marker,),
        )
