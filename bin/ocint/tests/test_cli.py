import json
import tomllib
from io import StringIO
from pathlib import Path

import pytest
from click.testing import CliRunner
from ocint._timeutil import make_window
from ocint.cli import main
from ocint.state.models import (
    StateDetailed,
    StateDetailedAgentUsage,
    StateDetailedProjectAgentUsage,
    StateDetailedProjectUsage,
)
from ocint.state.render import render_detailed
from rich.console import Console

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
    content = " ".join(table_result.output.split())
    assert "Detailed OpenCode usage" in content
    assert "Database:" in content
    assert "opencode.db" in content
    assert "Window: all" in content
    assert "Message-attributed cost: 43.000000" in content
    assert "By project" in content
    assert "Project Cost /work/automation 31.000000 /work/dotfiles 12.000000" in content
    assert "By agent" in content
    assert "Agent Cost historical-agent (subagent) 31.000000 historical-agent (root) 12.000000" in content
    assert "/work/automation: historical-agent (subagent) 31.000000" in content
    assert "/work/dotfiles: historical-agent (root) 12.000000" in content
    for excluded in ["Tokens", "Sessions", "Assistant messages", "Project ID", "Worktree"]:
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


def test_state_detailed_human_output_omits_zero_costs_and_separates_projects() -> None:
    # GIVEN positive and zero-cost detailed groups across two projects
    detailed = StateDetailed(
        db_path=Path("/tmp/opencode.db"),
        message_attributed_cost=5,
        projects=[
            StateDetailedProjectUsage(project_id="p1", worktree="/p1", cost=3),
            StateDetailedProjectUsage(project_id="p2", worktree="/p2", cost=2),
        ],
        agents=[
            StateDetailedAgentUsage(agent="build", kind="root", cost=3),
            StateDetailedAgentUsage(agent="zero-agent", kind="subagent", cost=0),
            StateDetailedAgentUsage(agent="plan", kind="root", cost=2),
        ],
        project_agents=[
            StateDetailedProjectAgentUsage(project_id="p1", worktree="/p1", agent="build", kind="root", cost=3),
            StateDetailedProjectAgentUsage(
                project_id="p1", worktree="/p1", agent="zero-agent", kind="subagent", cost=0
            ),
            StateDetailedProjectAgentUsage(project_id="p2", worktree="/p2", agent="plan", kind="root", cost=2),
        ],
    )
    output = StringIO()
    console = Console(file=output, force_terminal=False, width=120)

    # WHEN the concise human report is rendered
    console.print(render_detailed(detailed, make_window()))
    lines = output.getvalue().splitlines()

    # THEN zero costs are absent and a blank row separates project groups
    assert "zero-agent" not in output.getvalue()
    assert "0.000000" not in output.getvalue()
    first_project = next(index for index, line in enumerate(lines) if "/p1: build (root)" in line)
    second_project = next(index for index, line in enumerate(lines) if "/p2: plan (root)" in line)
    assert any(not line.strip() for line in lines[first_project + 1 : second_project])


@pytest.mark.parametrize(
    ("arguments", "heading"),
    [
        (("config", "--db", "{db}"), "OpenCode paths"),
        (("schema", "--db", "{db}"), "OpenCode database schema"),
        (("summary", "--db", "{db}"), "OpenCode usage summary"),
        (("detailed", "--db", "{db}"), "Detailed OpenCode usage"),
        (("sessions", "--db", "{db}"), "OpenCode session usage"),
        (("query", "--db", "{db}", "SELECT COUNT(*) AS sessions FROM session"), "OpenCode query results"),
    ],
)
def test_all_state_commands_render_friendly_human_output(
    tmp_path: Path, arguments: tuple[str, ...], heading: str
) -> None:
    # GIVEN a current OpenCode SQLite fixture
    db_path = create_opencode_db(tmp_path / "opencode.db")
    command = [argument.format(db=db_path) for argument in arguments]

    # WHEN each state command uses its default human format
    result = CliRunner().invoke(main, ["state", *command])

    # THEN the command renders its human-facing document
    assert result.exit_code == 0, result.output
    assert heading in result.output


@pytest.mark.parametrize(
    "arguments",
    [
        ("config", "--db", "{db}"),
        ("schema", "--db", "{db}"),
        ("summary", "--db", "{db}"),
        ("detailed", "--db", "{db}"),
        ("sessions", "--db", "{db}"),
        ("query", "--db", "{db}", "SELECT COUNT(*) AS sessions FROM session"),
    ],
)
def test_all_state_commands_keep_json_machine_readable(tmp_path: Path, arguments: tuple[str, ...]) -> None:
    # GIVEN a current OpenCode SQLite fixture
    db_path = create_opencode_db(tmp_path / "opencode.db")
    command = [argument.format(db=db_path) for argument in arguments]

    # WHEN each state command requests JSON
    result = CliRunner().invoke(main, ["state", *command, "--format", "json"])

    # THEN the complete output remains one machine-readable JSON value
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) is not None
    assert "OpenCode" not in result.output


def test_state_query_human_output_has_explicit_empty_state(tmp_path: Path) -> None:
    # GIVEN a current OpenCode SQLite fixture
    db_path = create_opencode_db(tmp_path / "opencode.db")

    # WHEN a read-only query returns no rows
    result = CliRunner().invoke(
        main,
        ["state", "query", "--db", str(db_path), "SELECT id FROM session WHERE 0"],
    )

    # THEN the human output explains that the result is empty
    assert result.exit_code == 0, result.output
    assert "OpenCode query results" in result.output
    assert "No rows" in result.output
