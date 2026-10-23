import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner
from ocint.cli import main
from ocint.ctx.config import resolve_ctx_refresh_config
from ocint.ctx.models import (
    CtxRefreshLogsAvailable,
    CtxRefreshLogsUnavailable,
    CtxRefreshStructuredLogEntry,
    CtxRefreshWorkerRequest,
)
from ocint.ctx.refresh.logging import read_refresh_logs
from ocint.ctx.refresh.scheduler import schedule_refresh_worker
from ocint.ctx.status import select_latest_actual_import_logs
from tests.support.opencode_db import create_opencode_db


def test_ctx_status_logs_shows_latest_actual_run_and_every_subsequent_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # GIVEN a ready index and interleaved refresh diagnostics around two actual imports
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    log_path = tmp_path / "ctx.sqlite.refresh.log"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    records = [
        {"event": "refresh_worker_scheduled", "run_id": "old", "pid": 1},
        {"event": "refresh_import_started", "run_id": "old", "pid": 2},
        {"event": "refresh_worker_scheduled", "run_id": "latest", "pid": 3, "ctx_db": "/exact_ctx"},
        {"event": "refresh_worker_scheduled", "run_id": "skipped", "pid": 4, "command": ["ocint", "worker"]},
        {"event": "refresh_skipped", "run_id": "skipped", "pid": 4, "reason": "lock_held"},
        {"event": "refresh_import_started", "run_id": "latest", "pid": 5, "source_db": "/exact_source"},
        {"event": "refresh_succeeded", "run_id": "latest", "pid": 5, "events_written": 7},
    ]
    lines = [json.dumps(record) for record in records]
    lines.insert(6, "worker emitted a non-JSON diagnostic")
    log_path.write_text("\n".join(lines) + "\n")

    # WHEN human status requests refresh logs
    result = runner.invoke(main, ["ctx", "status", "--logs"])

    # THEN status is followed by the full path and the selected, exact structured stream
    assert result.exit_code == 0, result.output
    compact_output = "".join(result.output.split())
    assert compact_output.index("Contextindexstatus") < compact_output.index(str(log_path))
    assert "run_id=old" not in result.output
    for value in [
        "refresh_worker_scheduled",
        "refresh_skipped",
        "refresh_import_started",
        "refresh_succeeded",
        "run_id=latest",
        "run_id=skipped",
        "pid=3",
        "ctx_db=/exact_ctx",
        "command=['ocint', 'worker']",
        "source_db=/exact_source",
        "events_written=7",
        "worker emitted a non-JSON diagnostic",
    ]:
        assert value in result.output


def test_ctx_status_logs_reports_missing_log_without_failing_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # GIVEN a ready index without a refresh log
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    runner = CliRunner()
    assert runner.invoke(main, ["ctx", "import"]).exit_code == 0

    # WHEN logs are requested
    result = runner.invoke(main, ["ctx", "status", "--logs"])

    # THEN status succeeds with a clear missing-log message
    assert result.exit_code == 0, result.output
    assert str(tmp_path / "ctx.sqlite.refresh.log") in "".join(result.output.split())
    assert "Refresh log does not exist." in result.output


def test_ctx_status_logs_reports_no_actual_import_without_failing_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # GIVEN a ready index with only a skipped worker attempt
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    log_path = tmp_path / "ctx.sqlite.refresh.log"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    runner = CliRunner()
    assert runner.invoke(main, ["ctx", "import"]).exit_code == 0
    log_path.write_text('{"event":"refresh_skipped","run_id":"skip","reason":"lock_held"}\n')

    # WHEN logs are requested
    result = runner.invoke(main, ["ctx", "status", "--logs"])

    # THEN status succeeds with a clear no-attempt message
    assert result.exit_code == 0, result.output
    assert "No actual refresh import attempt was found." in result.output


def test_latest_import_logs_uses_newest_import_with_matching_schedule(tmp_path: Path) -> None:
    # GIVEN a complete import followed by an orphaned import marker
    log_path = tmp_path / "refresh.log"
    records = [
        {"event": "refresh_worker_scheduled", "run_id": "complete"},
        {"event": "refresh_import_started", "run_id": "complete"},
        {"event": "refresh_succeeded", "run_id": "complete"},
        {"event": "refresh_import_started", "run_id": "orphan"},
    ]
    log_path.write_text("\n".join(json.dumps(record) for record in records) + "\n")

    # WHEN the latest complete import window is selected
    selected = select_latest_actual_import_logs(read_refresh_logs(log_path))

    # THEN selection starts at the complete run and retains every later record
    assert isinstance(selected, CtxRefreshLogsAvailable)
    structured = [entry for entry in selected.entries if isinstance(entry, CtxRefreshStructuredLogEntry)]
    assert structured[0].event == "refresh_worker_scheduled"
    assert structured[0].run_id == "complete"
    assert structured[-1].run_id == "orphan"


def test_latest_import_logs_reports_import_without_matching_schedule(tmp_path: Path) -> None:
    # GIVEN an import marker whose scheduling record has another run ID
    log_path = tmp_path / "refresh.log"
    log_path.write_text(
        '{"event":"refresh_worker_scheduled","run_id":"other"}\n{"event":"refresh_import_started","run_id":"orphan"}\n'
    )

    # WHEN the latest complete import window is selected
    selected = select_latest_actual_import_logs(read_refresh_logs(log_path))

    # THEN the malformed correlation is reported clearly
    assert isinstance(selected, CtxRefreshLogsUnavailable)
    assert selected.message == "No refresh import attempt with a matching scheduled event was found."


def test_ctx_status_rejects_logs_with_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # GIVEN status output flags that cannot be composed
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "unused.sqlite"))

    # WHEN both are passed
    result = CliRunner().invoke(main, ["ctx", "status", "--logs", "--json"])

    # THEN the conflict is rejected before status infrastructure is accessed
    assert result.exit_code != 0
    assert "--logs cannot be used with --json" in result.output
    assert "run `ocint ctx import` first" not in result.output


def test_scheduler_passes_generated_run_id_to_worker_and_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # GIVEN a scheduler with process creation recorded in memory
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "ocint.ctx.refresh.scheduler.subprocess.Popen",
        lambda command, **_kwargs: commands.append(command) or SimpleNamespace(pid=4321),
    )
    log_path = tmp_path / "refresh.log"

    # WHEN a refresh worker is scheduled
    pid = schedule_refresh_worker(
        ctx_db_path=tmp_path / "ctx.sqlite", source_db_path=tmp_path / "source.db", log_path=log_path
    )

    # THEN one generated run ID is shared by the hidden option and scheduling records
    logs = read_refresh_logs(log_path)
    selected = select_latest_actual_import_logs(logs)
    assert pid == 4321
    command = commands[0]
    run_id = command[command.index("--run-id") + 1]
    assert run_id
    assert "--log-jsonl" in command
    assert '"run_id":"' + run_id + '"' in log_path.read_text()
    assert "refresh_worker_scheduled" in log_path.read_text()
    records = [json.loads(line) for line in log_path.read_text().splitlines()]
    spawned = next(record for record in records if record["event"] == "refresh_worker_spawned")
    assert spawned["pid"] == 4321
    assert isinstance(selected, CtxRefreshLogsUnavailable)
    assert "No actual refresh import attempt" in selected.message


def test_worker_emits_run_id_and_actual_import_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # GIVEN a stale ready index and worker JSONL logging enabled
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    runner = CliRunner()
    assert runner.invoke(main, ["ctx", "import"]).exit_code == 0
    monkeypatch.setenv("OCINT_CTX_REFRESH_TTL", "0")

    # WHEN the hidden worker runs with its scheduler identity
    result = runner.invoke(main, ["ctx", "refresh-worker", "--run-id", "worker-run-7", "--log-jsonl"])

    # THEN every record carries that identity and actual work has an explicit marker
    assert result.exit_code == 0, result.output
    records = [json.loads(line) for line in result.output.splitlines()]
    assert records
    assert {record["run_id"] for record in records} == {"worker-run-7"}
    events = [record["event"] for record in records]
    assert events.index("refresh_import_started") < events.index("refresh_succeeded")


def test_worker_cli_constructs_typed_request_with_hidden_logging_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # GIVEN resolved worker paths and an orchestration recorder
    ctx_db = tmp_path / "ctx.sqlite"
    source_db = tmp_path / "source.db"
    requests: list[CtxRefreshWorkerRequest] = []
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setattr(
        "ocint.ctx.cli.run_refresh_worker",
        lambda request, _sql_config, _expected_revision: requests.append(request),
    )

    # WHEN Click parses the hidden worker controls
    result = CliRunner().invoke(main, ["ctx", "refresh-worker", "--run-id", "typed-run", "--log-jsonl"])

    # THEN the outer adapter passes one concrete typed request to orchestration
    assert result.exit_code == 0, result.output
    assert requests == [
        CtxRefreshWorkerRequest(
            ctx_db_path=ctx_db,
            source_db_path=source_db,
            refresh_config=resolve_ctx_refresh_config(ctx_db_path=ctx_db),
            run_id="typed-run",
            log_jsonl=True,
        )
    ]
