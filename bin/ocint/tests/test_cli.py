import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner
from ocint.cli import main


def test_root_help_lists_only_state_and_ctx_groups() -> None:
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "state" in result.output
    assert "ctx" in result.output
    assert "opencode_ctx" not in result.output


def test_pyproject_defines_only_ocint_script() -> None:
    package_root = Path(__file__).parents[1]
    data = tomllib.loads((package_root / "pyproject.toml").read_text())

    assert data["project"]["scripts"] == {"ocint": "ocint.cli:main"}


def test_ctx_help_exposes_no_provider_option() -> None:
    result = CliRunner().invoke(main, ["ctx", "search", "--help"])

    assert result.exit_code == 0
    assert "".join(["--", "provider"]) not in result.output


def test_state_help_exposes_only_supported_analytics_commands() -> None:
    # GIVEN the state command group
    # WHEN its help is requested
    result = CliRunner().invoke(main, ["state", "--help"])

    # THEN removed analytics commands are not available
    assert result.exit_code == 0
    assert "daily" not in result.output
    assert "models" not in result.output
    assert "summary" in result.output
    assert "sessions" in result.output


@pytest.mark.parametrize("command", ["summary", "sessions"])
def test_state_analytics_expose_days_but_not_date_range_options(command: str) -> None:
    # GIVEN a supported state analytics command
    # WHEN its help is requested
    result = CliRunner().invoke(main, ["state", command, "--help"])

    # THEN only OpenCode's days filter is exposed
    assert result.exit_code == 0
    assert "--days" in result.output
    assert "--since" not in result.output
    assert "--until" not in result.output
