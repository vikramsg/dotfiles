import json
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner
from ocint.cli import main

from tests.fixtures.opencode_db import create_opencode_db


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
    assert "detailed" in result.output


@pytest.mark.parametrize("command", ["summary", "sessions", "detailed"])
def test_state_analytics_expose_days_but_not_date_range_options(command: str) -> None:
    # GIVEN a supported state analytics command
    # WHEN its help is requested
    result = CliRunner().invoke(main, ["state", command, "--help"])

    # THEN only OpenCode's days filter is exposed
    assert result.exit_code == 0
    assert "--days" in result.output
    assert "--since" not in result.output
    assert "--until" not in result.output


def test_state_detailed_help_describes_message_time_accounting_without_grouping_option() -> None:
    # GIVEN the opt-in detailed state command
    # WHEN its help is requested
    result = CliRunner().invoke(main, ["state", "detailed", "--help"])

    # THEN its time source and fixed groupings are discoverable
    assert result.exit_code == 0
    assert "assistant messages created" in result.output
    assert "--group" not in result.output


def test_state_detailed_renders_fixed_readable_sections_and_structured_json(tmp_path: Path) -> None:
    # GIVEN a current OpenCode SQLite fixture
    db_path = create_opencode_db(tmp_path / "opencode.db")
    runner = CliRunner()

    # WHEN detailed usage is rendered in both supported formats
    table_result = runner.invoke(main, ["state", "detailed", "--db", str(db_path)])
    json_result = runner.invoke(main, ["state", "detailed", "--db", str(db_path), "--format", "json"])

    # THEN readable output has fixed detail-free sections and JSON preserves all structured groups
    assert table_result.exit_code == 0, table_result.output
    assert table_result.output == (
        f"DB: {db_path}\n"
        "WINDOW: all\n"
        "MESSAGE_ATTRIBUTED_COST: 43.000000\n"
        "\n"
        "BY PROJECT\n"
        "/work/automation: 31.000000\n"
        "/work/dotfiles: 12.000000\n"
        "\n"
        "BY AGENT\n"
        "historical-agent (subagent): 31.000000\n"
        "historical-agent (root): 12.000000\n"
        "\n"
        "BY PROJECT / AGENT\n"
        "/work/automation: historical-agent (subagent): 31.000000\n"
        "/work/dotfiles: historical-agent (root): 12.000000\n"
    )
    for excluded in ["TOKENS_", "SESSIONS", "ASSISTANT_MESSAGES", "PROJECT_ID", "WORKTREE"]:
        assert excluded not in table_result.output
    payload = json.loads(json_result.output)
    assert payload["message_attributed_cost"] == 43.0
    assert [row["project_id"] for row in payload["projects"]] == ["project-automation", "project-dotfiles"]
    assert [(row["agent"], row["kind"]) for row in payload["agents"]] == [
        ("historical-agent", "subagent"),
        ("historical-agent", "root"),
    ]
    assert [
        (
            row["project_id"],
            row["worktree"],
            row["agent"],
            row["kind"],
            row["sessions"],
            row["assistant_messages"],
            row["cost"],
            row["tokens"]["total"],
        )
        for row in payload["project_agents"]
    ] == [
        ("project-automation", "/work/automation", "historical-agent", "subagent", 1, 1, 31.0, 15),
        ("project-dotfiles", "/work/dotfiles", "historical-agent", "root", 1, 1, 12.0, 42),
    ]
