import json
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import click
from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text


GRAPHQL_QUERY = """
query($queryString: String!, $cursor: String) {
  search(query: $queryString, type: ISSUE, first: 100, after: $cursor) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        id
        additions
        deletions
        mergedAt
        repository { nameWithOwner }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class PullRequest:
    github_id: str
    merged_at: datetime
    repository: str
    additions: int
    deletions: int


@dataclass
class Aggregate:
    prs: int = 0
    additions: int = 0
    deletions: int = 0
    repositories: set[str] | None = None

    def __post_init__(self) -> None:
        if self.repositories is None:
            self.repositories = set()

    @property
    def net(self) -> int:
        return self.additions - self.deletions

    def add(self, pull_request: PullRequest) -> None:
        self.prs += 1
        self.additions += pull_request.additions
        self.deletions += pull_request.deletions
        assert self.repositories is not None
        self.repositories.add(pull_request.repository)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _run_gh(arguments: list[str]) -> Any:
    try:
        result = subprocess.run(
            ["gh", *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise click.ClickException(
            "GitHub CLI (gh) was not found; install it and authenticate first."
        ) from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "unknown error").strip()
        raise click.ClickException(f"gh command failed: {detail}") from error

    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise click.ClickException("gh returned malformed JSON.") from error


def fetch_authenticated_user() -> str:
    payload = _run_gh(["api", "user"])
    if not isinstance(payload, dict) or not isinstance(payload.get("login"), str):
        raise click.ClickException("gh returned malformed user data.")
    return payload["login"]


def _parse_pull_request(node: Any) -> PullRequest:
    try:
        github_id = node["id"]
        merged_at_raw = node["mergedAt"]
        repository = node["repository"]["nameWithOwner"]
        additions = node["additions"]
        deletions = node["deletions"]
        if (
            not isinstance(github_id, str)
            or not isinstance(merged_at_raw, str)
            or not isinstance(repository, str)
        ):
            raise TypeError
        if not isinstance(additions, int) or not isinstance(deletions, int):
            raise TypeError
        merged_at = datetime.fromisoformat(merged_at_raw.replace("Z", "+00:00"))
        if merged_at.tzinfo is None:
            raise ValueError
        return PullRequest(
            github_id,
            merged_at.astimezone(timezone.utc),
            repository,
            additions,
            deletions,
        )
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise click.ClickException(
            "gh returned malformed pull request data."
        ) from error


def _parse_search(payload: Any) -> tuple[int, list[Any], bool, str | None]:
    if not isinstance(payload, dict):
        raise click.ClickException("gh returned malformed GraphQL data.")
    errors = payload.get("errors")
    if errors:
        try:
            messages = "; ".join(str(error["message"]) for error in errors)
        except KeyError, TypeError:
            messages = "unknown error"
        raise click.ClickException(f"GraphQL error: {messages}")

    try:
        search = payload["data"]["search"]
        issue_count = search["issueCount"]
        nodes = search["nodes"]
        page_info = search["pageInfo"]
        has_next_page = page_info["hasNextPage"]
        end_cursor = page_info["endCursor"]
        if (
            not isinstance(issue_count, int)
            or not isinstance(nodes, list)
            or not isinstance(has_next_page, bool)
            or (end_cursor is not None and not isinstance(end_cursor, str))
        ):
            raise TypeError
    except (KeyError, TypeError) as error:
        raise click.ClickException("gh returned malformed GraphQL data.") from error
    return issue_count, nodes, has_next_page, end_cursor


def _graphql_search_page(
    user: str, start_day: date, end_day: date, cursor: str | None = None
) -> tuple[int, list[Any], bool, str | None]:
    escaped_user = user.replace("\\", "\\\\").replace('"', '\\"')
    search_query = (
        f'is:pr is:merged author:"{escaped_user}" '
        f"merged:{start_day.isoformat()}..{end_day.isoformat()}"
    )
    arguments = [
        "api",
        "graphql",
        "-f",
        f"query={GRAPHQL_QUERY}",
        "-f",
        f"queryString={search_query}",
    ]
    if cursor is not None:
        arguments.extend(["-f", f"cursor={cursor}"])
    return _parse_search(_run_gh(arguments))


def _fetch_date_range(user: str, start_day: date, end_day: date) -> list[PullRequest]:
    issue_count, nodes, has_next_page, cursor = _graphql_search_page(
        user, start_day, end_day
    )
    if issue_count > 1000:
        if start_day == end_day:
            raise click.ClickException(
                f"GitHub search matched {issue_count:,} pull requests on single day "
                f"{start_day.isoformat()}, exceeding the 1,000-result cap."
            )
        midpoint = start_day + timedelta(days=(end_day - start_day).days // 2)
        return _fetch_date_range(user, start_day, midpoint) + _fetch_date_range(
            user, midpoint + timedelta(days=1), end_day
        )

    pull_requests = [_parse_pull_request(node) for node in nodes]
    while has_next_page:
        if not cursor:
            raise click.ClickException("gh returned malformed GraphQL pagination data.")
        _, nodes, has_next_page, cursor = _graphql_search_page(
            user, start_day, end_day, cursor
        )
        pull_requests.extend(_parse_pull_request(node) for node in nodes)
    return pull_requests


def fetch_pull_requests(user: str, start: datetime, end: datetime) -> list[PullRequest]:
    if start.tzinfo is None or end.tzinfo is None or start > end:
        raise click.ClickException("Invalid UTC report range.")
    start_utc = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)
    candidates = _fetch_date_range(user, start_utc.date(), end_utc.date())
    pull_requests: list[PullRequest] = []
    seen_ids: set[str] = set()
    for pull_request in candidates:
        if (
            pull_request.github_id not in seen_ids
            and start_utc <= pull_request.merged_at <= end_utc
        ):
            seen_ids.add(pull_request.github_id)
            pull_requests.append(pull_request)

    return pull_requests


def week_start(value: datetime) -> date:
    utc_value = value.astimezone(timezone.utc)
    return (utc_value - timedelta(days=utc_value.weekday())).date()


def report_start(value: datetime, weeks: int) -> datetime:
    first_monday = week_start(value) - timedelta(weeks=weeks - 1)
    return datetime.combine(first_monday, time.min, tzinfo=timezone.utc)


def week_bucket_starts(start: datetime, weeks: int) -> list[date]:
    return [start.date() + timedelta(weeks=offset) for offset in range(weeks)]


def aggregate_pull_requests(
    pull_requests: list[PullRequest], per_repo: bool
) -> dict[date | tuple[date, str], Aggregate]:
    groups: defaultdict[date | tuple[date, str], Aggregate] = defaultdict(Aggregate)
    for pull_request in pull_requests:
        if per_repo:
            key = (week_start(pull_request.merged_at), pull_request.repository)
        else:
            key = week_start(pull_request.merged_at)
        groups[key].add(pull_request)
    return dict(groups)


def _number(value: int, style: str = "") -> Text:
    return Text(f"{value:,}", style=style, justify="right")


def _net(value: int) -> Text:
    style = "green" if value > 0 else "red" if value < 0 else "dim"
    prefix = "+" if value > 0 else ""
    return Text(f"{prefix}{value:,}", style=style, justify="right")


def render_results(
    pull_requests: list[PullRequest],
    per_repo: bool,
    bucket_starts: list[date],
    *,
    console: Console | None = None,
) -> None:
    if console is None:
        console = Console(file=click.get_text_stream("stdout"))
    groups = aggregate_pull_requests(pull_requests, per_repo)
    if not per_repo:
        for monday in bucket_starts:
            groups.setdefault(monday, Aggregate())
    title = "Merged Pull Requests"
    if per_repo:
        title += " by Repository"
    title += f" - Last {len(bucket_starts)} Weeks"
    table = Table(
        title=title,
        title_style="bold",
        header_style="bold cyan",
        border_style="bright_black",
        box=box.ROUNDED,
    )

    table.add_column("Week Start", width=10, min_width=10, max_width=10, no_wrap=True)
    if per_repo:
        table.add_column("Repository", overflow="fold")
    for column in ("PRs", "Added", "Deleted", "Net"):
        table.add_column(column, justify="right")
    if not per_repo:
        table.add_column("Repos", justify="right")

    group_rows = list(groups.items())
    if per_repo:
        group_rows.sort(
            key=lambda item: (item[0][0], -item[1].net, item[0][1].casefold())
        )
    else:
        group_rows.sort(key=lambda item: item[0])

    previous_week: date | None = None
    for key, aggregate in group_rows:
        if per_repo:
            assert isinstance(key, tuple)
            if previous_week is not None and key[0] != previous_week:
                table.add_section()
            previous_week = key[0]
            prefix: list[str | Text] = [
                Text(key[0].isoformat(), style="cyan"),
                Text(key[1], style="magenta"),
            ]
        else:
            assert isinstance(key, date)
            prefix = [Text(key.isoformat(), style="cyan")]
        table.add_row(
            *prefix,
            _number(aggregate.prs, "bold" if aggregate.prs else "dim"),
            _number(aggregate.additions, "green" if aggregate.additions else "dim"),
            _number(aggregate.deletions, "red" if aggregate.deletions else "dim"),
            _net(aggregate.net),
            *([_number(len(aggregate.repositories or set()))] if not per_repo else []),
            style="dim" if aggregate.prs == 0 else None,
        )
    console.print(table)


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--weeks",
    type=click.IntRange(min=1),
    default=10,
    show_default=True,
    help="Number of trailing weeks to include.",
)
@click.option(
    "--per-repo",
    is_flag=True,
    help="Show weekly rows for each repository with merged pull requests.",
)
def main(weeks: int, per_repo: bool) -> None:
    """Show merged pull request statistics using the authenticated GitHub CLI."""
    user = fetch_authenticated_user()
    end = utc_now()
    start = report_start(end, weeks)
    pull_requests = fetch_pull_requests(user, start, end)
    render_results(
        pull_requests,
        per_repo,
        week_bucket_starts(start, weeks),
    )


if __name__ == "__main__":
    main()
