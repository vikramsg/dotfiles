import tomllib
from pathlib import Path

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
