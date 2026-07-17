import json
import re
import subprocess
from datetime import date, datetime, timezone
from io import StringIO

import pytest
from click.testing import CliRunner
from rich.console import Console

from gh_stats import cli


NOW = datetime(2026, 7, 17, 12, tzinfo=timezone.utc)


def pr(
    merged_at: str,
    repo: str,
    additions: int,
    deletions: int,
    github_id: str | None = None,
) -> cli.PullRequest:
    return cli.PullRequest(
        github_id=github_id or f"{repo}:{merged_at}",
        merged_at=datetime.fromisoformat(merged_at.replace("Z", "+00:00")),
        repository=repo,
        additions=additions,
        deletions=deletions,
    )


def test_default_view_uses_10_weeks_and_monday_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {}
    monkeypatch.setattr(cli, "utc_now", lambda: NOW)
    monkeypatch.setattr(cli, "fetch_authenticated_user", lambda: "octocat")

    def fake_fetch(user, start, end):
        calls.update(user=user, start=start, end=end)
        return [pr("2026-07-15T09:00:00Z", "acme/widgets", 10, 3)]

    monkeypatch.setattr(cli, "fetch_pull_requests", fake_fetch)

    result = CliRunner().invoke(cli.main)

    assert result.exit_code == 0
    assert calls["user"] == "octocat"
    assert calls["end"] == NOW
    assert calls["start"] == datetime(2026, 5, 11, tzinfo=timezone.utc)
    assert "╭" in result.output
    assert "Week Start" in result.output
    assert "2026-07-13" in result.output
    assert "2026-W29" not in result.output
    assert "acme/widgets" not in result.output
    assert len(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", result.output)) == 10


def test_week_view_has_exactly_n_monday_buckets_including_inactive_weeks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "utc_now", lambda: NOW)
    monkeypatch.setattr(cli, "fetch_authenticated_user", lambda: "octocat")
    monkeypatch.setattr(
        cli,
        "fetch_pull_requests",
        lambda user, start, end: [pr("2026-07-07T09:00:00Z", "acme/api", 3, 1)],
    )

    starts = cli.week_bucket_starts(datetime(2026, 6, 29, tzinfo=timezone.utc), 3)
    assert starts == [date(2026, 6, 29), date(2026, 7, 6), date(2026, 7, 13)]

    result = CliRunner().invoke(cli.main, ["--weeks", "3"])

    assert result.exit_code == 0
    for monday in ("2026-06-29", "2026-07-06", "2026-07-13"):
        assert result.output.count(monday) == 1
    assert "2026-07-13 │   0" in result.output


def test_per_repo_view_calculates_weekly_repository_aggregates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pull_requests = [
        pr("2026-07-15T09:00:00Z", "acme/widgets", 10, 3),
        pr("2026-07-08T09:00:00Z", "acme/widgets", 4, 9),
        pr("2026-07-14T09:00:00Z", "acme/api", 8, 1),
    ]
    monkeypatch.setattr(cli, "utc_now", lambda: NOW)
    monkeypatch.setattr(cli, "fetch_authenticated_user", lambda: "octocat")
    monkeypatch.setattr(
        cli,
        "fetch_pull_requests",
        lambda user, start, end: pull_requests,
    )

    groups = cli.aggregate_pull_requests(pull_requests, per_repo=True)
    widgets_week = (date(2026, 7, 13), "acme/widgets")
    assert (groups[widgets_week].prs, groups[widgets_week].additions) == (1, 10)

    result = CliRunner().invoke(
        cli.main,
        [
            "--weeks",
            "2",
            "--per-repo",
        ],
    )

    assert result.exit_code == 0
    assert "Repository" in result.output
    assert "acme/widgets" in result.output
    assert "acme/api" in result.output
    assert "2026-07-06" in result.output
    assert "2026-07-13" in result.output
    assert "Overall Summary" not in result.output


def test_per_repo_view_only_shows_rows_with_prs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "utc_now", lambda: NOW)
    monkeypatch.setattr(cli, "fetch_authenticated_user", lambda: "octocat")
    monkeypatch.setattr(
        cli,
        "fetch_pull_requests",
        lambda user, start, end: [pr("2026-07-07T09:00:00Z", "acme/api", 3, 1)],
    )

    result = CliRunner().invoke(cli.main, ["--weeks", "3", "--per-repo"])

    assert result.exit_code == 0
    assert "2026-07-06" in result.output
    assert "acme/api" in result.output
    assert "2026-06-29" not in result.output
    assert "2026-07-13" not in result.output


def test_per_repo_view_separates_weeks_and_sorts_each_week_by_net(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pull_requests = [
        pr("2026-07-06T09:00:00Z", "acme/lower-net", 10, 8),
        pr("2026-07-07T09:00:00Z", "acme/higher-net", 20, 1),
        pr("2026-07-13T09:00:00Z", "acme/next-week", 5, 1),
    ]
    monkeypatch.setattr(cli, "utc_now", lambda: NOW)
    monkeypatch.setattr(cli, "fetch_authenticated_user", lambda: "octocat")
    monkeypatch.setattr(
        cli, "fetch_pull_requests", lambda user, start, end: pull_requests
    )

    result = CliRunner().invoke(cli.main, ["--weeks", "2", "--per-repo"])

    assert result.exit_code == 0
    assert result.output.index("acme/higher-net") < result.output.index(
        "acme/lower-net"
    )
    assert result.output.index("acme/lower-net") < result.output.index("acme/next-week")
    assert result.output.count("├") == 2


def test_weeks_must_be_positive() -> None:
    result = CliRunner().invoke(cli.main, ["--weeks", "0"])

    assert result.exit_code == 2
    assert "x>=1" in result.output


def test_cli_reports_gh_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(cli.subprocess, "run", missing)
    result = CliRunner().invoke(cli.main)
    assert result.exit_code == 1
    assert "GitHub CLI (gh) was not found" in result.output


def test_fetch_rejects_graphql_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    completed = subprocess.CompletedProcess(
        [], 0, json.dumps({"errors": [{"message": "bad query"}]}), ""
    )
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: completed)

    with pytest.raises(cli.click.ClickException, match="GraphQL error: bad query"):
        cli.fetch_pull_requests("octocat", NOW - cli.timedelta(weeks=1), NOW)


def graphql_payload(
    issue_count: int,
    nodes: list[dict] | None = None,
    *,
    has_next_page: bool = False,
    end_cursor: str | None = None,
) -> dict:
    return {
        "data": {
            "search": {
                "issueCount": issue_count,
                "nodes": nodes or [],
                "pageInfo": {
                    "hasNextPage": has_next_page,
                    "endCursor": end_cursor,
                },
            }
        }
    }


def graphql_node(github_id: str, merged_at: str = "2026-07-10T12:00:00Z") -> dict:
    return {
        "id": github_id,
        "mergedAt": merged_at,
        "repository": {"nameWithOwner": "acme/api"},
        "additions": 3,
        "deletions": 1,
    }


def query_string(arguments: list[str]) -> str:
    return next(
        argument.removeprefix("queryString=")
        for argument in arguments
        if argument.startswith("queryString=")
    )


def test_fetch_uses_bounded_search_and_paginates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    responses = iter(
        [
            graphql_payload(
                2, [graphql_node("PR1")], has_next_page=True, end_cursor="next"
            ),
            graphql_payload(2, [graphql_node("PR2", "2026-07-11T12:00:00Z")]),
        ]
    )

    def fake_run(arguments):
        calls.append(arguments)
        return next(responses)

    monkeypatch.setattr(cli, "_run_gh", fake_run)
    result = cli.fetch_pull_requests(
        "octocat",
        datetime(2026, 7, 7, 6, tzinfo=timezone.utc),
        NOW,
    )

    assert [item.github_id for item in result] == ["PR1", "PR2"]
    assert "merged:2026-07-07..2026-07-17" in query_string(calls[0])
    assert "cursor=next" in calls[1]


def test_fetch_preserves_exact_timestamp_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "_run_gh",
        lambda arguments: graphql_payload(
            3,
            [
                graphql_node("EARLY", "2026-07-07T05:59:59Z"),
                graphql_node("IN", "2026-07-07T06:00:00Z"),
                graphql_node("LATE", "2026-07-17T12:00:01Z"),
            ],
        ),
    )

    result = cli.fetch_pull_requests(
        "octocat", datetime(2026, 7, 7, 6, tzinfo=timezone.utc), NOW
    )

    assert [item.github_id for item in result] == ["IN"]


def test_capped_search_partitions_on_days_and_deduplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queries: list[str] = []

    def fake_run(arguments):
        query = query_string(arguments)
        queries.append(query)
        if "merged:2026-07-07..2026-07-17" in query:
            return graphql_payload(1001)
        if "merged:2026-07-07..2026-07-12" in query:
            return graphql_payload(1, [graphql_node("SAME")])
        if "merged:2026-07-13..2026-07-17" in query:
            return graphql_payload(1, [graphql_node("SAME", "2026-07-14T12:00:00Z")])
        raise AssertionError(query)

    monkeypatch.setattr(cli, "_run_gh", fake_run)
    result = cli.fetch_pull_requests(
        "octocat", datetime(2026, 7, 7, tzinfo=timezone.utc), NOW
    )

    assert len(result) == 1
    assert len(queries) == 3
    assert any("merged:2026-07-07..2026-07-12" in query for query in queries)
    assert any("merged:2026-07-13..2026-07-17" in query for query in queries)


def test_fetch_rejects_single_day_over_github_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "data": {
            "search": {
                "issueCount": 1001,
                "nodes": [],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        }
    }
    monkeypatch.setattr(cli, "_run_gh", lambda arguments: payload)

    with pytest.raises(cli.click.ClickException, match="single day 2026-07-17.*1,000"):
        cli.fetch_pull_requests(
            "octocat",
            datetime(2026, 7, 17, tzinfo=timezone.utc),
            NOW,
        )


@pytest.mark.parametrize("per_repo", [False, True])
def test_narrow_output_keeps_full_monday_date(per_repo: bool) -> None:
    output = StringIO()
    console = Console(file=output, width=60, no_color=True)

    cli.render_results(
        [pr("2026-07-15T09:00:00Z", "acme/a-very-long-repository-name", 10, 3)],
        per_repo,
        [date(2026, 7, 13)],
        console=console,
    )

    assert "2026-07-13" in output.getvalue()
    assert "2026-\n" not in output.getvalue()


def test_fetch_rejects_malformed_output(monkeypatch: pytest.MonkeyPatch) -> None:
    completed = subprocess.CompletedProcess([], 0, "not json", "")
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: completed)

    with pytest.raises(cli.click.ClickException, match="malformed JSON"):
        cli.fetch_authenticated_user()


def test_help_only_describes_agreed_options() -> None:
    result = CliRunner().invoke(cli.main, ["--help"])

    assert result.exit_code == 0
    assert "--weeks INTEGER RANGE" in result.output
    assert "[default: 10;" in result.output
    assert "x>=1]" in result.output
    assert "--per-repo" in result.output
    for removed_option in ("--group-by", "--summary", "--no-color", "--user"):
        assert removed_option not in result.output
