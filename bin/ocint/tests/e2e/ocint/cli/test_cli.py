import json
import subprocess
import sys
from collections import UserDict
from collections.abc import Mapping
from pathlib import Path

import pytest
from tests.support.opencode_db import create_opencode_db


@pytest.fixture
def cli_environment(tmp_path: Path) -> Mapping[str, str]:
    return UserDict(HOME=str(tmp_path))


@pytest.fixture
def ocint_executable() -> Path:
    return Path(sys.executable).with_name("ocint")


@pytest.fixture
def default_opencode_db(tmp_path: Path) -> Path:
    db_path = tmp_path / ".local" / "share" / "opencode" / "opencode.db"
    db_path.parent.mkdir(parents=True)
    return create_opencode_db(db_path)


def test_state_config_discovers_default_database(
    tmp_path: Path, default_opencode_db: Path, cli_environment: Mapping[str, str], ocint_executable: Path
) -> None:
    # GIVEN a synthetic database at the default location with no path overrides
    # WHEN the actual CLI process requests config without --db
    result = subprocess.run(
        [ocint_executable, "state", "config", "--format", "json"],
        cwd=tmp_path,
        env=cli_environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    # THEN the exact existing default path is reported
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["db_path"] == str(default_opencode_db)
    assert payload["db_exists"] is True


def test_state_summary_reads_default_database(
    tmp_path: Path, default_opencode_db: Path, cli_environment: Mapping[str, str], ocint_executable: Path
) -> None:
    # GIVEN known session aggregates in the default database
    # WHEN the actual CLI process requests summary without --db
    result = subprocess.run(
        [ocint_executable, "state", "summary", "--format", "json"],
        cwd=tmp_path,
        env=cli_environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    # THEN real database discovery and querying return the fixture's authoritative totals
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["db_path"] == str(default_opencode_db)
    assert payload["sessions"] == 2
    assert payload["messages"] == 2
    assert payload["cost"] == 30.0
    assert payload["tokens"]["total"] == 435


def test_state_detailed_reads_default_database(
    tmp_path: Path, default_opencode_db: Path, cli_environment: Mapping[str, str], ocint_executable: Path
) -> None:
    # GIVEN known assistant messages in the default database
    # WHEN the actual CLI process requests detailed without --db
    result = subprocess.run(
        [ocint_executable, "state", "detailed", "--format", "json"],
        cwd=tmp_path,
        env=cli_environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    # THEN real database discovery and querying preserve message-attributed usage
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["db_path"] == str(default_opencode_db)
    assert payload["opencode_total_cost"] == 30.0
    assert payload["message_attributed_cost"] == 43.0
    assert [row["project_id"] for row in payload["projects"]] == ["project-automation", "project-dotfiles"]


@pytest.mark.parametrize("command", ["summary", "detailed"])
def test_state_missing_default_database_fails_without_creating_it(
    tmp_path: Path, cli_environment: Mapping[str, str], ocint_executable: Path, command: str
) -> None:
    # GIVEN an isolated home with no database or path overrides
    expected = tmp_path / ".local" / "share" / "opencode" / "opencode.db"

    # WHEN the actual CLI process requests analytics without --db
    result = subprocess.run(
        [ocint_executable, "state", command],
        cwd=tmp_path,
        env=cli_environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    # THEN the error identifies the shared default and does not create a database
    assert result.returncode != 0
    assert f"OpenCode DB does not exist: {expected}" in result.stderr
    assert not expected.exists()
    assert not (tmp_path / "Library" / "Application Support" / "opencode" / "opencode.db").exists()
