import json
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner
from ocint.cli import main
from ocint.ctx.db import current_ctx_head_revision
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

    sources = CliRunner().invoke(main, ["ctx", "sources", "--json"])
    assert sources.exit_code == 0
    assert {row["provider"] for row in json.loads(sources.output)} == {"opencode"}
    assert json.loads(sources.output)[0]["name"] == "OpenCode DB"


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
