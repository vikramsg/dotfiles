import inspect
import json
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner
from ocint.cli import main
from ocint.ctx.search import search_history
from sqlalchemy import create_engine, text
from tests.fixtures.opencode_db import create_opencode_db


def test_search_defaults_to_primary_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)
    runner = CliRunner()

    results = runner.invoke(main, ["ctx", "search", "subagent only marker"])

    assert results.exit_code == 0, results.output
    assert results.output == "No results\n"

    subagent_results = runner.invoke(main, ["ctx", "search", "subagent only marker", "--include-subagents"])
    assert subagent_results.exit_code == 0, subagent_results.output
    assert "s-sub" in subagent_results.output


def test_search_filters_by_file_workspace_session_since_and_terms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(
        main,
        [
            "ctx",
            "search",
            "native event marker",
            "--workspace",
            "repo-directory-only",
            "--file",
            "AGENTS.md",
            "--session",
            "s-primary",
            "--since",
            "30d",
            "--term",
            "related term",
            "--term",
            "error text",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "evt_native_tool" in result.output
    assert "session=s-primary" in result.output
    assert "path=AGENTS.md" in result.output


def test_search_file_filter_matches_all_payload_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)
    runner = CliRunner()

    for file_filter in [
        "bin/ocint/ocint/ctx/search.py",
        "implementation_notes.md",
        "bin/ocint/tests/ctx/test_sql.py",
    ]:
        result = runner.invoke(main, ["ctx", "search", "file.patch", "--file", file_filter])

        assert result.exit_code == 0, result.output
        assert "evt_native_patch" in result.output


def test_search_applies_terms_before_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    _add_term_limit_fixture_rows(source_db)
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "missing-opencode.db"))

    result = runner.invoke(
        main,
        ["ctx", "search", "candidate window marker", "--term", "deep required term", "--limit", "1"],
    )

    assert result.exit_code == 0, result.output
    assert "evt_old_required_term" in result.output


def test_search_semantics_match_across_backends(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _skip_if_duckdb_fts_unavailable(tmp_path)
    source_db = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))
    monkeypatch.setenv("OCINT_CTX_DUCKDB", str(tmp_path / "ctx.duckdb"))
    runner = CliRunner()
    for backend in ["sqlite", "duckdb"]:
        imported = runner.invoke(main, ["ctx", "--backend", backend, "import", "--source-db", str(source_db)])
        assert imported.exit_code == 0, imported.output

    args = [
        "ctx",
        "--backend",
        "sqlite",
        "search",
        "native event marker",
        "--workspace",
        "repo-directory-only",
        "--file",
        "AGENTS.md",
        "--session",
        "s-primary",
        "--since",
        "30d",
        "--term",
        "related term",
        "--term",
        "error text",
        "--refresh",
        "off",
        "--json",
    ]
    sqlite_results = runner.invoke(main, args)
    duckdb_results = runner.invoke(main, ["ctx", "--backend", "duckdb", *args[3:]])

    assert sqlite_results.exit_code == 0, sqlite_results.output
    assert duckdb_results.exit_code == 0, duckdb_results.output
    assert [row["event_id"] for row in json.loads(sqlite_results.output)] == ["evt_native_tool"]
    assert json.loads(duckdb_results.output) == json.loads(sqlite_results.output)


def test_search_history_contract_is_explicit() -> None:
    signature = inspect.signature(search_history)

    assert list(signature.parameters) == ["request", "repository"]
    assert all(parameter.kind is not inspect.Parameter.VAR_POSITIONAL for parameter in signature.parameters.values())
    assert all(parameter.kind is not inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values())


def _import_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_db = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))
    imported = CliRunner().invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "missing-opencode.db"))


def _add_term_limit_fixture_rows(source_db: Path) -> None:
    base_time = 2_000_000_000_000
    rows = [
        (
            "evt_old_required_term",
            "s-primary",
            10_000,
            "note.created",
            json.dumps(
                {
                    "sessionID": "s-primary",
                    "timestamp": base_time,
                    "text": "candidate window marker deep required term",
                    "path": "term-limit-valid.txt",
                }
            ),
        )
    ]
    rows.extend(
        (
            f"evt_new_decoy_{index:03d}",
            "s-primary",
            10_001 + index,
            "note.created",
            json.dumps(
                {
                    "sessionID": "s-primary",
                    "timestamp": base_time + 1_000 + index,
                    "text": "candidate window marker decoy text",
                    "path": f"term-limit-decoy-{index:03d}.txt",
                }
            ),
        )
        for index in range(105)
    )
    with sqlite3.connect(source_db) as connection:
        connection.executemany("INSERT INTO event VALUES (?, ?, ?, ?, ?)", rows)


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
