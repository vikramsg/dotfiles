import base64
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
    assert queries[1]["project"] == ["p&1"]
    assert queries[0]["from"] == queries[1]["from"]
    assert queries[0]["to"] == queries[1]["to"]
    assert int(queries[0]["to"][0]) - int(queries[0]["from"][0]) == 7 * 86400000


@pytest.mark.parametrize("arguments", [[], ["--days", "0"], ["--days", "7"]])
def test_terminal_report_has_project_model_and_token_usage(api_server, cli_environment, executable, arguments):
    # GIVEN a service with cost and token usage
    # WHEN a human-readable report is requested
    result = subprocess.run([executable, *arguments], env=cli_environment, text=True, capture_output=True, check=False)
    # THEN the required breakdowns are present, without ANSI in redirected output
    assert result.returncode == 0, result.stderr
    for text in ["OpenCode usage", "dotfiles", "azure", "medium", "other", "default", "$12.125000", "8,000"]:
        assert text in result.stdout
    assert "\x1b[" not in result.stdout
    assert "fixture-password" not in result.stdout + result.stderr


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
