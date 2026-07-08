import json
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner
from ocint.cli import main
from ocint.ctx.db import current_ctx_head_revision, migrate_ctx_db
from ocint.ctx.search import CtxSearchRepository
from ocint.ctx.sql import CtxSqlRepository
from ocint.ctx.sql.models import default_ctx_sql_config, stable_view_create_statements
from ocint.ctx.status import CtxStatusRepository
from tests.fixtures.opencode_db import create_opencode_db


def test_ctx_status_and_sources_are_opencode_only_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(db_path))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))
    imported = CliRunner().invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "missing-opencode.db"))

    status = CliRunner().invoke(main, ["ctx", "status", "--json"])
    assert status.exit_code == 0
    status_payload = json.loads(status.output)
    assert status_payload["provider"] == "opencode"
    assert status_payload["db_path"] == str(tmp_path / "ctx.sqlite")
    assert status_payload["index_ready"] is True
    assert status_payload["sessions"] == 2
    assert status_payload["primary_sessions"] == 1
    assert status_payload["source_db_exists"] is False
    assert status_payload["refresh_ttl_ms"] == 3_600_000
    assert status_payload["refresh_freshness"] == "fresh"
    assert status_payload["latest_attempt_status"] == "success"
    assert status_payload["latest_success_completed_at"] is not None
    assert status_payload["checkpoint_summary"]

    sources = CliRunner().invoke(main, ["ctx", "sources", "--json"])
    assert sources.exit_code == 0
    assert {row["provider"] for row in json.loads(sources.output)} == {"opencode"}
    assert json.loads(sources.output)[0]["name"] == "OpenCode DB"
    assert json.loads(sources.output)[0]["imported_at"] == status_payload["latest_success_completed_at"]


def test_ctx_status_output_does_not_vary_with_current_opencode_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    alternate_db = create_opencode_db(tmp_path / "alternate-opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    runner = CliRunner()

    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output

    payloads = []
    for current_db in [source_db, alternate_db, tmp_path / "missing-opencode.db"]:
        monkeypatch.setenv("OPENCODE_DB", str(current_db))
        status = runner.invoke(main, ["ctx", "status", "--json"])
        assert status.exit_code == 0, status.output
        payloads.append(json.loads(status.output))

    assert payloads[0] == payloads[1] == payloads[2]
    assert payloads[0]["index_ready"] is True
    assert payloads[0]["sessions"] == 2
    assert payloads[0]["source_db_path"] is None
    assert payloads[0]["source_db_exists"] is False


def test_ctx_status_refresh_summary_uses_one_explicit_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_a = create_opencode_db(tmp_path / "source-a.db")
    source_b = create_opencode_db(tmp_path / "source-b.db")
    ctx_db = tmp_path / "ctx.sqlite"
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    runner = CliRunner()
    for source in [source_a, source_b]:
        monkeypatch.setenv("OPENCODE_DB", str(source))
        imported = runner.invoke(main, ["ctx", "import"])
        assert imported.exit_code == 0, imported.output
    _force_mixed_refresh_states(ctx_db, source_a=source_a, source_b=source_b)
    monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "missing-opencode.db"))

    status = runner.invoke(main, ["ctx", "status", "--json"])

    assert status.exit_code == 0, status.output
    payload = json.loads(status.output)
    assert payload["refresh_source_path"] == str(source_b)
    assert payload["latest_attempt_status"] == "failed"
    assert payload["latest_attempt_started_at"] == 2_000
    assert payload["latest_success_completed_at"] is None
    assert payload["checkpoint_summary"] is None
    assert payload["refresh_freshness"] == "unknown"
    rows_by_path = {row["source_path"]: row for row in payload["refresh_sources"]}
    assert rows_by_path[str(source_a)]["latest_success_completed_at"] == 1_000
    assert rows_by_path[str(source_a)]["latest_attempt_status"] == "success"
    assert rows_by_path[str(source_b)]["latest_attempt_status"] == "failed"
    assert rows_by_path[str(source_b)]["latest_success_completed_at"] is None


def test_ctx_status_and_sources_fail_fast_without_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx_db = tmp_path / "missing.sqlite"
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))

    status = CliRunner().invoke(main, ["ctx", "status", "--json"])
    sources = CliRunner().invoke(main, ["ctx", "sources", "--json"])

    assert status.exit_code != 0
    assert "run `ocint ctx import` first" in status.output
    assert sources.exit_code != 0
    assert "run `ocint ctx import` first" in sources.output
    assert not ctx_db.exists()


def test_ctx_read_commands_fail_fast_when_existing_ctx_db_is_unmigrated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx_db = tmp_path / "unmigrated.sqlite"
    sqlite3.connect(ctx_db).close()
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))

    runner = CliRunner()
    commands = [
        ["ctx", "status"],
        ["ctx", "status", "--json"],
        ["ctx", "sources"],
        ["ctx", "sources", "--json"],
        ["ctx", "search", "native event marker", "--refresh", "off"],
    ]

    for command in commands:
        result = runner.invoke(main, command)
        assert result.exit_code != 0, result.output
        assert "run `ocint ctx import` first" in result.output


@pytest.mark.parametrize("drop_sql", ["DROP VIEW ctx_events", "DROP TABLE ctx_event_fts"])
def test_ctx_search_fails_when_existing_index_is_missing_required_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drop_sql: str
) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    with sqlite3.connect(ctx_db) as connection:
        connection.execute(drop_sql)

    result = runner.invoke(main, ["ctx", "search", "native event marker", "--refresh", "off"])

    assert result.exit_code != 0
    assert "run `ocint ctx import` first" in result.output


@pytest.mark.parametrize("revision", ["0001_ctx_index", "bogus_revision"])
def test_ctx_readiness_rejects_non_current_alembic_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, revision: str
) -> None:
    runner, ctx_db = _import_ctx_fixture(tmp_path, monkeypatch)
    with sqlite3.connect(ctx_db) as connection:
        connection.execute("UPDATE alembic_version SET version_num = ?", (revision,))

    _assert_read_commands_require_import(
        runner,
        [
            ["ctx", "status", "--json"],
            ["ctx", "sources", "--json"],
            ["ctx", "search", "native event marker", "--refresh", "off"],
        ],
    )


@pytest.mark.parametrize(
    "revision_rows",
    [(), (current_ctx_head_revision(), "bogus_revision")],
    ids=["empty", "multiple"],
)
def test_ctx_readiness_rejects_empty_or_multiple_alembic_revision_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, revision_rows: tuple[str, ...]
) -> None:
    runner, ctx_db = _import_ctx_fixture(tmp_path, monkeypatch)
    with sqlite3.connect(ctx_db) as connection:
        connection.execute("DELETE FROM alembic_version")
        connection.executemany("INSERT INTO alembic_version(version_num) VALUES (?)", [(row,) for row in revision_rows])

    _assert_read_commands_require_import(
        runner,
        [
            ["ctx", "status", "--json"],
            ["ctx", "search", "native event marker", "--refresh", "off"],
        ],
    )


def test_ctx_readiness_rejects_name_compatible_malformed_physical_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx_db = tmp_path / "malformed.sqlite"
    _create_name_compatible_malformed_ctx_db(ctx_db)
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))

    result = CliRunner().invoke(main, ["ctx", "status", "--json"])

    assert result.exit_code != 0
    assert "run `ocint ctx import` first" in result.output
    assert '"index_ready": true' not in result.output


def test_ctx_migration_moves_refresh_metadata_out_of_ctx_source(tmp_path: Path) -> None:
    ctx_db = tmp_path / "old-head.sqlite"
    imported_at = 1_783_421_234_000
    checkpoint = '{"mtime_ns": 10, "size": 20}'
    _create_old_head_ctx_db(ctx_db, imported_at=imported_at, checkpoint=checkpoint)

    migrate_ctx_db(ctx_db)

    with sqlite3.connect(ctx_db) as connection:
        assert (
            connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == current_ctx_head_revision()
        )
        source_columns = {row[1] for row in connection.execute("PRAGMA table_info(ctx_source)")}
        assert "imported_at" not in source_columns
        assert "checkpoint_payload" not in source_columns
        row = connection.execute(
            """
            SELECT latest_attempt_started_at,
                   latest_attempt_completed_at,
                   latest_attempt_status,
                   latest_success_started_at,
                   latest_success_completed_at,
                   latest_success_checkpoint_payload
            FROM ctx_refresh_state
            """
        ).fetchone()
        assert row == (imported_at, imported_at, "success", imported_at, imported_at, checkpoint)
        derived = connection.execute("SELECT imported_at FROM ctx_sources").fetchone()[0]
        assert derived == imported_at


def test_ctx_readiness_rejects_malformed_fts_columns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner, ctx_db = _import_ctx_fixture(tmp_path, monkeypatch)
    with sqlite3.connect(ctx_db) as connection:
        connection.execute("DROP TABLE ctx_event_fts")
        connection.execute("CREATE VIRTUAL TABLE ctx_event_fts USING fts5(search_text)")

    _assert_read_commands_require_import(
        runner,
        [["ctx", "search", "native event marker", "--refresh", "off"]],
    )


def test_ctx_readiness_rejects_regular_table_named_ctx_event_fts_before_row_loaders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, ctx_db = _import_ctx_fixture(tmp_path, monkeypatch)
    with sqlite3.connect(ctx_db) as connection:
        connection.execute("DROP TABLE ctx_event_fts")
        connection.execute(
            "CREATE TABLE ctx_event_fts(search_text TEXT, event_pk INTEGER, event_id TEXT, source_table TEXT)"
        )

    def fail_if_read_loader_runs(*_args: object, **_kwargs: object) -> None:
        pytest.fail("read loader should not run when ctx readiness fails")

    monkeypatch.setattr(CtxStatusRepository, "status", fail_if_read_loader_runs)
    monkeypatch.setattr(CtxStatusRepository, "sources", fail_if_read_loader_runs)
    monkeypatch.setattr(CtxSearchRepository, "search_events", fail_if_read_loader_runs)
    monkeypatch.setattr(CtxSqlRepository, "load_stable_projection_rows", fail_if_read_loader_runs)

    _assert_read_commands_require_import(
        runner,
        [
            ["ctx", "status"],
            ["ctx", "sources"],
            ["ctx", "search", "native event marker", "--refresh", "off"],
            ["ctx", "sql", "SELECT provider FROM ctx_sources"],
        ],
    )


def test_ctx_readiness_rejects_stable_view_with_missing_columns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, ctx_db = _import_ctx_fixture(tmp_path, monkeypatch)
    with sqlite3.connect(ctx_db) as connection:
        connection.execute("DROP VIEW ctx_events")
        connection.execute('CREATE VIEW ctx_events AS SELECT provider AS "provider" FROM ctx_event')

    _assert_read_commands_require_import(runner, [["ctx", "status", "--json"]])


def test_ctx_readiness_rejects_stable_view_with_same_columns_but_wrong_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, ctx_db = _import_ctx_fixture(tmp_path, monkeypatch)
    with sqlite3.connect(ctx_db) as connection:
        connection.execute("DROP VIEW ctx_events")
        connection.execute(
            """
            CREATE VIEW ctx_events AS
            SELECT provider AS "provider",
                   provider_session_id AS "provider_session_id",
                   event_id AS "event_id",
                   source_table AS "source_table",
                   event_type AS "event_type",
                   time_created AS "time_created",
                   payload_json AS "text",
                   source_path AS "source_path",
                   citation AS "citation"
            FROM ctx_event
            """
        )

    result = runner.invoke(
        main,
        ["ctx", "sql", "SELECT text FROM ctx_events WHERE event_id = 'p-primary-step'", "--format", "json"],
    )

    assert result.exit_code != 0
    assert "run `ocint ctx import` first" in result.output
    assert "sessionID" not in result.output


def test_ctx_rejects_provider_option(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(db_path))
    provider_option = "".join(["--", "provider"])

    result = CliRunner().invoke(main, ["ctx", "search", "ctx skill", provider_option, "opencode"])

    assert result.exit_code != 0
    assert "No such option" in result.output
    assert provider_option in result.output


def _import_ctx_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[CliRunner, Path]:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    ctx_db = tmp_path / "ctx.sqlite"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "missing-opencode.db"))
    return runner, ctx_db


def _assert_read_commands_require_import(runner: CliRunner, commands: list[list[str]]) -> None:
    for command in commands:
        result = runner.invoke(main, command)
        assert result.exit_code != 0, result.output
        assert "run `ocint ctx import` first" in result.output
        assert '"index_ready": true' not in result.output


def _force_mixed_refresh_states(ctx_db: Path, *, source_a: Path, source_b: Path) -> None:
    with sqlite3.connect(ctx_db) as connection:
        rows = {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT source_path, id FROM ctx_source WHERE source_path IN (?, ?)", (str(source_a), str(source_b))
            )
        }
        source_a_id = rows[str(source_a)]
        source_b_id = rows[str(source_b)]
        connection.execute(
            """
            UPDATE ctx_refresh_state
            SET latest_attempt_started_at = 1_000,
                latest_attempt_completed_at = 1_001,
                latest_attempt_status = 'success',
                latest_success_started_at = 999,
                latest_success_completed_at = 1_000,
                latest_success_checkpoint_payload = 'source-a-checkpoint',
                source_watermark_payload = 'source-a-watermark',
                latest_failed_at = NULL,
                latest_error_message = NULL
            WHERE source_id = ?
            """,
            (source_a_id,),
        )
        connection.execute(
            """
            UPDATE ctx_refresh_state
            SET latest_attempt_started_at = 2_000,
                latest_attempt_completed_at = 2_001,
                latest_attempt_status = 'failed',
                latest_success_started_at = NULL,
                latest_success_completed_at = NULL,
                latest_success_checkpoint_payload = NULL,
                source_watermark_payload = NULL,
                latest_failed_at = 2_001,
                latest_error_message = 'source-b-failed'
            WHERE source_id = ?
            """,
            (source_b_id,),
        )


def _create_old_head_ctx_db(ctx_db: Path, *, imported_at: int, checkpoint: str) -> None:
    with sqlite3.connect(ctx_db) as connection:
        connection.executescript(
            """
            CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);
            INSERT INTO alembic_version(version_num) VALUES ('20260704_create_ctx_index');
            CREATE TABLE ctx_source (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              provider VARCHAR NOT NULL,
              source_type VARCHAR NOT NULL,
              name VARCHAR NOT NULL,
              source_path TEXT NOT NULL,
              imported_at BIGINT NOT NULL,
              sessions INTEGER NOT NULL,
              events INTEGER NOT NULL,
              checkpoint_payload TEXT,
              CONSTRAINT uq_ctx_source_identity UNIQUE (provider, source_type, source_path)
            );
            CREATE TABLE ctx_session (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              source_id INTEGER NOT NULL,
              provider VARCHAR NOT NULL,
              provider_session_id VARCHAR NOT NULL,
              session_id VARCHAR NOT NULL,
              parent_id VARCHAR,
              title TEXT,
              workspace TEXT,
              time_created BIGINT,
              time_updated BIGINT,
              source_path TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              CONSTRAINT uq_ctx_session_source_native UNIQUE (source_id, provider_session_id)
            );
            CREATE TABLE ctx_event (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              source_id INTEGER NOT NULL,
              provider VARCHAR NOT NULL,
              provider_session_id VARCHAR,
              event_id VARCHAR NOT NULL,
              source_table VARCHAR NOT NULL,
              message_id VARCHAR,
              event_type VARCHAR NOT NULL,
              time_created BIGINT,
              time_updated BIGINT,
              source_path TEXT,
              full_text TEXT NOT NULL,
              search_text TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              citation TEXT NOT NULL,
              CONSTRAINT uq_ctx_event_source_native UNIQUE (source_id, source_table, event_id)
            );
            CREATE TABLE ctx_file_touched (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              source_id INTEGER NOT NULL,
              provider VARCHAR NOT NULL,
              path TEXT NOT NULL,
              provider_session_id VARCHAR,
              event_id VARCHAR NOT NULL,
              source_table VARCHAR NOT NULL,
              CONSTRAINT uq_ctx_file_source_event_path UNIQUE (source_id, source_table, event_id, path)
            );
            CREATE VIRTUAL TABLE ctx_event_fts USING fts5(search_text, event_pk UNINDEXED, event_id UNINDEXED, source_table UNINDEXED);
            CREATE VIEW ctx_sources AS SELECT provider, source_type, name, source_path AS path, sessions, events, imported_at FROM ctx_source;
            """
        )
        connection.execute(
            """
            INSERT INTO ctx_source(provider, source_type, name, source_path, imported_at, sessions, events, checkpoint_payload)
            VALUES ('opencode', 'sqlite', 'OpenCode DB', '/tmp/opencode.db', ?, 0, 0, ?)
            """,
            (imported_at, checkpoint),
        )


def _create_name_compatible_malformed_ctx_db(ctx_db: Path) -> None:
    with sqlite3.connect(ctx_db) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        connection.execute("INSERT INTO alembic_version(version_num) VALUES (?)", (current_ctx_head_revision(),))
        for table in ["ctx_source", "ctx_session", "ctx_event", "ctx_file_touched"]:
            connection.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE VIRTUAL TABLE ctx_event_fts USING fts5("
            "search_text, event_pk UNINDEXED, event_id UNINDEXED, source_table UNINDEXED)"
        )
        for statement in stable_view_create_statements(default_ctx_sql_config()):
            connection.execute(statement)
