import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from ocint.cli import main
from tests.fixtures.opencode_db import create_opencode_db


def test_ctx_status_and_sources_are_opencode_only_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(db_path))

    status = CliRunner().invoke(main, ["ctx", "status", "--json"])
    assert status.exit_code == 0
    status_payload = json.loads(status.output)
    assert status_payload["provider"] == "opencode"
    assert status_payload["sessions"] == 2
    assert status_payload["primary_sessions"] == 1

    sources = CliRunner().invoke(main, ["ctx", "sources", "--json"])
    assert sources.exit_code == 0
    assert {row["provider"] for row in json.loads(sources.output)} == {"opencode"}


def test_ctx_rejects_provider_option(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(db_path))
    provider_option = "".join(["--", "provider"])

    result = CliRunner().invoke(main, ["ctx", "search", "ctx skill", provider_option, "opencode"])

    assert result.exit_code != 0
    assert "No such option" in result.output
    assert provider_option in result.output
