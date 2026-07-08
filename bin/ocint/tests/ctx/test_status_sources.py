import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from ocint.cli import main
from sqlalchemy import create_engine, text
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


def test_ctx_status_and_sources_exit_zero_without_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "missing.sqlite"))

    status = CliRunner().invoke(main, ["ctx", "status", "--json"])
    sources = CliRunner().invoke(main, ["ctx", "sources", "--json"])

    assert status.exit_code == 0, status.output
    assert json.loads(status.output)["db_exists"] is False
    assert sources.exit_code == 0, sources.output
    assert json.loads(sources.output) == []


@pytest.mark.parametrize("backend", ["sqlite", "duckdb"])
def test_ctx_status_and_sources_work_for_backend(backend: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if backend == "duckdb":
        _skip_if_duckdb_fts_unavailable(tmp_path)
    db_path = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(db_path))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))
    monkeypatch.setenv("OCINT_CTX_DUCKDB", str(tmp_path / "ctx.duckdb"))
    imported = CliRunner().invoke(main, ["ctx", "--backend", backend, "import"])
    assert imported.exit_code == 0, imported.output

    status = CliRunner().invoke(main, ["ctx", "--backend", backend, "status", "--json"])
    sources = CliRunner().invoke(main, ["ctx", "--backend", backend, "sources", "--json"])

    assert status.exit_code == 0, status.output
    assert sources.exit_code == 0, sources.output
    assert json.loads(status.output)["sessions"] == 2
    assert json.loads(status.output)["primary_sessions"] == 1
    assert json.loads(sources.output)[0]["events"] > 0


def test_ctx_rejects_provider_option(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(db_path))
    provider_option = "".join(["--", "provider"])

    result = CliRunner().invoke(main, ["ctx", "search", "ctx skill", provider_option, "opencode"])

    assert result.exit_code != 0
    assert "No such option" in result.output
    assert provider_option in result.output


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
