import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from ocint.cli import main
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


def test_ctx_status_and_sources_exit_zero_without_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "missing.sqlite"))

    status = CliRunner().invoke(main, ["ctx", "status", "--json"])
    sources = CliRunner().invoke(main, ["ctx", "sources", "--json"])

    assert status.exit_code == 0, status.output
    assert json.loads(status.output)["db_exists"] is False
    assert sources.exit_code == 0, sources.output
    assert json.loads(sources.output) == []


def test_ctx_rejects_provider_option(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(db_path))
    provider_option = "".join(["--", "provider"])

    result = CliRunner().invoke(main, ["ctx", "search", "ctx skill", provider_option, "opencode"])

    assert result.exit_code != 0
    assert "No such option" in result.output
    assert provider_option in result.output
