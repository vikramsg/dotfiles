import json
import sqlite3
import time
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

import opencode_state.config as config_module
from opencode_state.cli import main
from opencode_state.config import resolve_paths
from opencode_state.db import open_readonly_connection, run_select_query, safe_select_query
from opencode_state.stats import daily_usage, make_window, session_usage


def create_usage_db(path: Path, now_ms: int | None = None) -> Path:
    now_ms = now_ms or int(time.time() * 1000)
    con = sqlite3.connect(path)
    con.execute(
        """
        CREATE TABLE message (
          id TEXT PRIMARY KEY,
          data TEXT NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE part (
          id TEXT PRIMARY KEY,
          message_id TEXT NOT NULL,
          session_id TEXT NOT NULL,
          time_created INTEGER NOT NULL,
          time_updated INTEGER NOT NULL,
          data TEXT NOT NULL
        )
        """
    )
    con.executemany(
        "INSERT INTO message VALUES (?, ?)",
        [
            ("m1", json.dumps({"role": "assistant", "providerID": "anthropic", "modelID": "claude-sonnet-4-5"})),
            ("m2", json.dumps({"role": "assistant", "providerID": "openai", "modelID": "gpt-5.5"})),
            ("m3", json.dumps({"role": "user"})),
        ],
    )
    rows = [
        (
            "p1",
            "m1",
            "s1",
            now_ms,
            now_ms,
            {
                "type": "step-finish",
                "cost": 1.25,
                "tokens": {
                    "input": 1_000_000,
                    "output": 2_000_000,
                    "reasoning": 30,
                    "cache": {"read": 40, "write": 50},
                    "total": 1_234_567,
                },
                "model": "wrong-part-model-alpha",
            },
        ),
        (
            "p2",
            "m2",
            "s1",
            now_ms,
            now_ms,
            {
                "type": "step-finish",
                "cost": 2.5,
                "tokens": {
                    "input": 1,
                    "output": 2,
                    "reasoning": 3,
                    "cache": {"read": 4, "write": 5},
                },
                "model": "wrong-part-model-beta",
            },
        ),
        (
            "p3",
            "m3",
            "s2",
            now_ms,
            now_ms,
            {"type": "message", "cost": 100, "tokens": {"input": 100, "total": 999_999_999}},
        ),
    ]
    con.executemany(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
        [(*row[:5], json.dumps(row[5])) for row in rows],
    )
    con.commit()
    con.close()
    return path

def test_config_cli_shows_explicit_config_and_db(tmp_path):
    config_file = tmp_path / "opencode.json"
    db_file = tmp_path / "state.db"
    config_file.write_text("{}")
    db_file.write_text("")

    result = CliRunner().invoke(
        main,
        ["config", "--config", str(config_file), "--db", str(db_file)],
    )

    assert result.exit_code == 0
    assert str(config_file) in result.output
    assert str(db_file) in result.output


def test_env_path_resolution_uses_overrides_and_data_dir_for_relative_db(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    data_home = tmp_path / "data"
    monkeypatch.setenv("OPENCODE_CONFIG", str(config_file))
    monkeypatch.setenv("OPENCODE_DB", "relative.db")
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg_config"))

    paths = resolve_paths()

    assert paths.config_path == config_file
    assert paths.db_path == data_home / "opencode" / "relative.db"


def test_resolve_paths_empty_env_does_not_fallback_to_process_env(tmp_path, monkeypatch):
    process_config = tmp_path / "process-opencode.json"
    process_db = tmp_path / "process-opencode.db"
    xdg_config_home = tmp_path / "xdg-config"
    xdg_data_home = tmp_path / "xdg-data"
    monkeypatch.setenv("OPENCODE_CONFIG", str(process_config))
    monkeypatch.setenv("OPENCODE_DB", str(process_db))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_config_home))
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg_data_home))

    paths = resolve_paths(env={}, cwd=tmp_path)

    assert paths.config_path != process_config
    assert paths.config_path != xdg_config_home / "opencode" / "opencode.json"
    assert paths.db_path != process_db
    assert paths.db_path != xdg_data_home / "opencode" / "opencode.db"


def test_explicit_empty_env_uses_cwd_without_reading_process_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "process-home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "process-xdg-config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "process-xdg-data"))

    def fail_home(cls):
        raise AssertionError("Path.home() should not be called for explicit env")

    monkeypatch.setattr(config_module.Path, "home", classmethod(fail_home))

    paths = resolve_paths(env={}, cwd=tmp_path)

    assert paths.config_path == tmp_path / ".config" / "opencode" / "opencode.json"
    if config_module.sys.platform == "darwin":
        assert paths.db_path == tmp_path / "Library" / "Application Support" / "opencode" / "opencode.db"
    else:
        assert paths.db_path == tmp_path / ".local" / "share" / "opencode" / "opencode.db"


def test_explicit_env_tilde_paths_use_explicit_home_not_process_home(tmp_path, monkeypatch):
    process_home = tmp_path / "process-home"
    explicit_home = tmp_path / "explicit-home"
    monkeypatch.setenv("HOME", str(process_home))

    paths = resolve_paths(
        env={
            "HOME": str(explicit_home),
            "OPENCODE_CONFIG": "~/opencode.json",
            "OPENCODE_DB": "~/state.db",
            "XDG_CONFIG_HOME": "~/xdg-config",
            "XDG_DATA_HOME": "~/xdg-data",
        },
        cwd=tmp_path,
    )

    assert paths.config_path == explicit_home / "opencode.json"
    assert paths.db_path == explicit_home / "state.db"
    assert not str(paths.config_path).startswith(str(process_home))
    assert not str(paths.db_path).startswith(str(process_home))

    xdg_paths = resolve_paths(
        env={
            "HOME": str(explicit_home),
            "XDG_CONFIG_HOME": "~/xdg-config",
            "XDG_DATA_HOME": "~/xdg-data",
        },
        cwd=tmp_path,
    )

    assert xdg_paths.config_path == explicit_home / "xdg-config" / "opencode" / "opencode.json"
    assert xdg_paths.db_path == explicit_home / "xdg-data" / "opencode" / "opencode.db"
    assert not str(xdg_paths.config_path).startswith(str(process_home))
    assert not str(xdg_paths.db_path).startswith(str(process_home))


def test_summary_fails_clearly_for_missing_db(tmp_path):
    missing = tmp_path / "missing.db"

    result = CliRunner().invoke(main, ["summary", "--db", str(missing)])

    assert result.exit_code != 0
    assert str(missing) in result.output


def test_cli_rejects_memory_db_argument_before_absolutizing():
    result = CliRunner().invoke(main, ["summary", "--db", ":memory:"])

    assert result.exit_code != 0
    assert ":memory: is not a valid OpenCode DB target" in result.output
    assert "/:memory:" not in result.output


def test_config_cli_rejects_memory_db_argument():
    result = CliRunner().invoke(main, ["config", "--db", ":memory:"])

    assert result.exit_code != 0
    assert ":memory: is not a valid OpenCode DB target" in result.output
    assert "/:memory:" not in result.output


def test_cli_rejects_memory_db_from_env(monkeypatch):
    monkeypatch.setenv("OPENCODE_DB", ":memory:")

    result = CliRunner().invoke(main, ["summary"])

    assert result.exit_code != 0
    assert ":memory: is not a valid OpenCode DB target" in result.output
    assert "/:memory:" not in result.output


def test_memory_db_is_rejected():
    with pytest.raises(ValueError, match=":memory:"):
        open_readonly_connection(":memory:")


def test_readonly_connection_allows_reads_and_rejects_writes(tmp_path):
    db_file = create_usage_db(tmp_path / "usage.db")

    con = open_readonly_connection(db_file)
    try:
        assert con.execute("SELECT count(*) FROM part").fetchone()[0] == 3
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            con.execute("INSERT INTO part VALUES ('x', 'm', 's', 0, 0, '{}')")
    finally:
        con.close()


def test_summary_json_aggregates_step_finish_rows_only(tmp_path):
    db_file = create_usage_db(tmp_path / "usage.db")

    result = CliRunner().invoke(main, ["summary", "--db", str(db_file), "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["sessions"] == 1
    assert payload["llm_steps"] == 2
    assert payload["cost"] == 3.75
    assert payload["tokens"] == {
        "input": 1_000_001,
        "output": 2_000_002,
        "reasoning": 33,
        "cache_read": 44,
        "cache_write": 55,
        "total": 1_234_582,
    }
    assert isinstance(payload["tokens"]["total"], int)


def test_summary_table_includes_human_labels(tmp_path):
    db_file = create_usage_db(tmp_path / "usage.db")

    result = CliRunner().invoke(main, ["summary", "--db", str(db_file), "--format", "table"])

    assert result.exit_code == 0
    assert "DB" in result.output
    assert "WINDOW" in result.output
    assert "SESSIONS" in result.output
    assert "LLM_STEPS" in result.output
    assert "COST" in result.output
    assert "TOKENS_TOTAL" in result.output
    assert "TOKENS_INPUT: 1,000,001" in result.output
    assert "TOKENS_OUTPUT: 2,000,002" in result.output
    assert "TOKENS_TOTAL: 1,234,582" in result.output


def test_stats_return_typed_domain_output_models(tmp_path):
    timestamp_ms = 1_704_067_200_000
    db_file = create_usage_db(tmp_path / "usage.db", now_ms=timestamp_ms)
    window = make_window()

    con = open_readonly_connection(db_file)
    try:
        daily_rows = daily_usage(con, window=window)
        session_rows = session_usage(con, window=window)
    finally:
        con.close()

    assert daily_rows[0].day == date(2024, 1, 1)
    assert isinstance(daily_rows[0].day, date)
    assert session_rows[0].first_seen == datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    assert isinstance(session_rows[0].first_seen, datetime)
    assert session_rows[0].last_seen == datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    assert isinstance(session_rows[0].last_seen, datetime)

    daily_result = CliRunner().invoke(main, ["daily", "--db", str(db_file), "--format", "json"])
    assert daily_result.exit_code == 0
    assert json.loads(daily_result.output)[0]["day"] == "2024-01-01"

    sessions_result = CliRunner().invoke(main, ["sessions", "--db", str(db_file), "--format", "json"])
    assert sessions_result.exit_code == 0
    sessions_payload = json.loads(sessions_result.output)
    assert sessions_payload[0]["first_seen"] == "2024-01-01T00:00:00Z"
    assert sessions_payload[0]["last_seen"] == "2024-01-01T00:00:00Z"


def test_make_window_days_anchor_to_until_and_rejects_inverted_ranges():
    window = make_window(days=7, until="2024-01-31")

    assert window.since == date(2024, 1, 25)
    assert window.until == date(2024, 1, 31)

    with pytest.raises(ValueError, match="--since must be on or before --until"):
        make_window(since="2024-02-01", until="2024-01-31")


def test_models_use_message_provider_and_model_metadata(tmp_path):
    db_file = create_usage_db(tmp_path / "usage.db")

    result = CliRunner().invoke(main, ["models", "--db", str(db_file), "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload == [
        {
            "provider": "openai",
            "model": "gpt-5.5",
            "sessions": 1,
            "llm_steps": 1,
            "cost": 2.5,
            "tokens": {
                "input": 1,
                "output": 2,
                "reasoning": 3,
                "cache_read": 4,
                "cache_write": 5,
                "total": 15,
            },
        },
        {
            "provider": "anthropic",
            "model": "claude-sonnet-4-5",
            "sessions": 1,
            "llm_steps": 1,
            "cost": 1.25,
            "tokens": {
                "input": 1_000_000,
                "output": 2_000_000,
                "reasoning": 30,
                "cache_read": 40,
                "cache_write": 50,
                "total": 1_234_567,
            },
        },
    ]
    assert "wrong-part-model" not in result.output


def test_query_returns_rows_and_rejects_destructive_sql(tmp_path):
    db_file = create_usage_db(tmp_path / "usage.db")
    runner = CliRunner()

    result = runner.invoke(
        main,
        ["query", "select session_id from part order by id limit 1", "--db", str(db_file), "--format", "json"],
    )
    assert result.exit_code == 0
    assert json.loads(result.output) == [{"session_id": "s1"}]

    for sql in [
        "insert into part values ('x', 'm', 's', 0, 0, '{}')",
        "update part set session_id = 'x'",
        "delete from part",
        "drop table part",
        "alter table part rename to old_part",
        "vacuum",
        "attach database 'x.db' as x",
        "select 1; select 2",
    ]:
        with pytest.raises(ValueError):
            safe_select_query(sql)


def test_query_allows_readonly_keywords_in_literals_and_functions(tmp_path):
    db_file = create_usage_db(tmp_path / "usage.db")

    result = CliRunner().invoke(
        main,
        [
            "query",
            "select replace('drop value', 'drop', 'keep') as value",
            "--db",
            str(db_file),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == [{"value": "keep value"}]


def test_run_select_query_rejects_mutating_with_statement_without_mutation(tmp_path):
    db_file = create_usage_db(tmp_path / "usage.db")
    con = sqlite3.connect(db_file)
    con.row_factory = sqlite3.Row

    try:
        before = con.execute("SELECT count(*) FROM part").fetchone()[0]
        with pytest.raises((ValueError, sqlite3.DatabaseError)):
            run_select_query(
                con,
                "WITH target AS (SELECT id FROM part LIMIT 1) "
                "DELETE FROM part WHERE id IN (SELECT id FROM target)",
            )
        after = con.execute("SELECT count(*) FROM part").fetchone()[0]
    finally:
        con.close()

    assert after == before
