import base64
import copy
import json
import subprocess
from pathlib import Path

import pytest


def test_json_preserves_responses_and_authenticates_using_registration(
    api_server, cli_environment, executable, tmp_path
):
    # GIVEN a local service registered in XDG_STATE_HOME
    # WHEN the executable fetches a seven-day JSON report outside the repo
    result = subprocess.run(
        [executable, "--days", "7", "--json"],
        env=cli_environment,
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    # THEN it authenticates, attributes usage, and preserves fields it doesn't render
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert report["requestMetadata"] == {"preserve": True}
    assert report["data"]["activity"] == api_server["payload"]["data"]["activity"]
    assert report["data"]["cost"] == 12.1250004
    assert report["projects"][0]["project"] == api_server["projects"][0]
    assert report["projects"][0]["usage"] == {key: value for key, value in report.items() if key != "projects"}
    requests = api_server["requests"]
    expected_auth = "Basic " + base64.b64encode(b"opencode:fixture-password").decode()
    assert all(request[2] == expected_auth for request in requests)
    assert {request[0] for request in requests} == {"/api/project", "/api/session/stats"}
    queries = [query for path, query, _ in requests if path == "/api/session/stats"]
    assert len(queries) == 2
    overall_query = next(query for query in queries if "project" not in query)
    project_query = next(query for query in queries if "project" in query)
    assert project_query["project"] == ["p&1"]
    assert overall_query["from"] == project_query["from"]
    assert overall_query["to"] == project_query["to"]
    assert int(overall_query["to"][0]) - int(overall_query["from"][0]) == 7 * 86400000


@pytest.mark.parametrize("arguments", [[], ["--days", "0"], ["--days", "7"]])
def test_terminal_report_defaults_to_compact_project_and_model_costs(
    api_server, cli_environment, executable, arguments
):
    # GIVEN a service with cost and token usage
    # WHEN a human-readable report is requested
    result = subprocess.run([executable, *arguments], env=cli_environment, text=True, capture_output=True, check=False)
    # THEN the required breakdowns are present, without ANSI in redirected output
    assert result.returncode == 0, result.stderr
    for text in [
        "OpenCode usage",
        "By project",
        "By model",
        "dotfiles",
        "azure",
        "medium",
        "other",
        "default",
        "$12.125000",
    ]:
        assert text in result.stdout
    assert "Total tokens" not in result.stdout
    assert "M = million tokens (rounded to 2 decimals)" not in result.stdout
    assert len(result.stdout.splitlines()) <= 30
    assert "\x1b[" not in result.stdout
    assert "fixture-password" not in result.stdout + result.stderr


def test_verbose_terminal_report_includes_token_usage(api_server, cli_environment, executable):
    result = subprocess.run([executable, "--verbose"], env=cli_environment, text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
    assert "Total tokens" in result.stdout
    assert "0.01M" in result.stdout
    assert "M = million tokens (rounded to 2 decimals)" not in result.stdout


@pytest.mark.parametrize("selector", ["p&1", "/work/dotfiles", "dotfiles"])
def test_exclude_project_removes_selected_usage_from_json_totals(api_server, cli_environment, executable, selector):
    # GIVEN a report whose only usage belongs to the selected project
    zero_usage = copy.deepcopy(api_server["payload"])
    data = zero_usage["data"]
    data.update({"cost": 0, "sessions": 0, "subagents": 0, "prompts": 0, "steps": 0, "models": []})
    data["tokens"] = {"input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}}
    api_server["projects"].append({"id": "archive", "canonical": "/work/archive", "sandboxes": []})
    api_server["project_payloads"] = {"archive": zero_usage}
    # WHEN selecting it by each supported selector form
    result = subprocess.run(
        [executable, "--json", "--exclude-project", selector],
        env=cli_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    # THEN its project row and all accounted usage are removed
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert [row["project"]["id"] for row in report["projects"]] == ["archive"]
    assert {field: report["data"][field] for field in ("cost", "sessions", "subagents", "prompts", "steps")} == {
        "cost": 0,
        "sessions": 0,
        "subagents": 0,
        "prompts": 0,
        "steps": 0,
    }
    assert report["data"]["tokens"] == {
        "input": 0,
        "output": 0,
        "reasoning": 0,
        "cache": {"read": 0, "write": 0},
    }
    assert report["data"]["models"] == []
    assert report["data"]["activity"] == []
    assert report["data"]["activeDays"] == 0
    assert report["data"]["streak"] == 0
    assert report["data"]["tools"]["totals"] == {"calls": 0, "succeeded": 0, "failed": 0, "unfinished": 0}


def test_exclusion_accounts_for_duplicate_model_rows(api_server, cli_environment, executable):
    # GIVEN duplicate rows for the same provider, model, and variant identity
    duplicate = copy.deepcopy(api_server["payload"]["data"]["models"][0])
    api_server["payload"]["data"]["models"].append(duplicate)
    # WHEN the project containing both rows is excluded
    result = subprocess.run(
        [executable, "--json", "--exclude-project", "dotfiles"],
        env=cli_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    # THEN neither duplicate remains in the adjusted model breakdown
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["data"]["models"] == []


def test_repeated_exclusions_adjust_terminal_and_json_reports(api_server, cli_environment, executable):
    # GIVEN a report with two projects and all usage attributed to one of them
    zero_usage = copy.deepcopy(api_server["payload"])
    data = zero_usage["data"]
    data.update({"cost": 0, "sessions": 0, "subagents": 0, "prompts": 0, "steps": 0, "models": []})
    data["tokens"] = {"input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}}
    api_server["projects"].append({"id": "archive", "canonical": "/work/archive", "sandboxes": []})
    api_server["project_payloads"] = {"archive": zero_usage}
    arguments = ["--exclude-project", "p&1", "--exclude-project", "p&1", "--exclude-project", "archive"]
    # WHEN one selector is repeated and every project is excluded
    json_result = subprocess.run(
        [executable, "--json", *arguments], env=cli_environment, text=True, capture_output=True, check=False
    )
    terminal_result = subprocess.run(
        [executable, "--verbose", *arguments], env=cli_environment, text=True, capture_output=True, check=False
    )
    # THEN both outputs represent the adjusted empty report
    assert json_result.returncode == terminal_result.returncode == 0
    assert json.loads(json_result.stdout)["projects"] == []
    assert "No project usage in this window." in terminal_result.stdout
    assert "No model usage." in terminal_result.stdout


@pytest.mark.parametrize(
    ("selector", "message"),
    [("missing", "Unknown project selector"), ("dotfiles", "Ambiguous project selector")],
)
def test_invalid_exclude_project_never_emits_partial_report(api_server, cli_environment, executable, selector, message):
    # GIVEN an unknown selector or a basename shared by multiple projects
    if selector == "dotfiles":
        api_server["projects"].append({"id": "other", "canonical": "/other/dotfiles", "sandboxes": []})
    # WHEN requesting an exclusion
    result = subprocess.run(
        [executable, "--json", "--exclude-project", selector],
        env=cli_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    # THEN selection fails before any report is printed
    assert result.returncode == 1
    assert result.stdout == ""
    assert message in result.stderr


@pytest.mark.parametrize(
    "arguments", [["--days", "-1"], ["--days", "1.5"], ["--days"], ["--days", "1000000"], ["--wat"]]
)
def test_invalid_arguments_never_contact_service(api_server, cli_environment, executable, arguments):
    # GIVEN invalid input
    # WHEN invoking the command
    result = subprocess.run([executable, *arguments], env=cli_environment, text=True, capture_output=True, check=False)
    # THEN it fails before making requests
    assert result.returncode == 2
    assert api_server["requests"] == []


def test_help_works_without_registration(cli_environment, executable):
    # GIVEN no running or registered service
    # WHEN asking for help
    result = subprocess.run([executable, "--help"], env=cli_environment, text=True, capture_output=True, check=False)
    # THEN usage remains discoverable
    assert result.returncode == 0
    assert "--days" in result.stdout
    assert "--json" in result.stdout
    assert "--verbose" in result.stdout
    assert "--exclude-project" in result.stdout


@pytest.mark.parametrize("arguments", [[], ["--json"]])
def test_project_failure_never_emits_partial_report(api_server, cli_environment, executable, arguments):
    # GIVEN overall statistics succeed but a project's request fails
    api_server["project_status"] = 500
    # WHEN assembling the report
    result = subprocess.run([executable, *arguments], env=cli_environment, text=True, capture_output=True, check=False)
    # THEN no overall-only result is presented as complete
    assert result.returncode == 1
    assert result.stdout == ""
    assert "HTTP 500" in result.stderr
    assert "do not echo" not in result.stderr


def test_missing_registration_is_an_error_not_zero_usage(cli_environment, executable):
    # GIVEN no service registration
    # WHEN fetching usage
    result = subprocess.run([executable], env=cli_environment, text=True, capture_output=True, check=False)
    # THEN a useful error replaces a misleading empty report
    assert result.returncode == 1
    assert result.stdout == ""
    assert "Start OpenCode V2" in result.stderr


@pytest.mark.parametrize("xdg", [None, ""])
def test_default_registration_path_is_resolved_at_cli_boundary(api_server, cli_environment, executable, xdg):
    # GIVEN no usable XDG override and a service registered under HOME
    if xdg is None:
        cli_environment.pop("XDG_STATE_HOME")
    else:
        cli_environment["XDG_STATE_HOME"] = xdg
    path = Path(cli_environment["HOME"]) / ".local/state/opencode/service.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"url": api_server["url"], "password": "fixture-password"}))
    # WHEN the real executable resolves its configuration
    result = subprocess.run([executable, "--json"], env=cli_environment, text=True, capture_output=True, check=False)
    # THEN it reaches the registered service without a hard-coded port
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["data"]["cost"] == api_server["payload"]["data"]["cost"]
    assert api_server["requests"]
