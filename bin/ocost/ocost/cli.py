"""Compose one complete report before emitting terminal or JSON output."""

import json
import os
import time
from pathlib import Path

import click
from rich.console import Console

from ocost.api import API, APIError, Connection
from ocost.models import ProjectUsage, Report
from ocost.render import render_report
from ocost.report import ProjectSelectionError, exclude_projects, resolve_projects
from ocost.window import Window


def fetch_report(api: API, window: Window, excluded_projects: tuple[str, ...] = ()) -> Report:
    discovered_projects = api.projects()
    excluded_ids = resolve_projects(discovered_projects, excluded_projects)
    projects = [ProjectUsage(project, api.stats(window, project=project.id)) for project in discovered_projects]
    overall = api.stats(window)
    return exclude_projects(Report(overall, projects), excluded_ids)


@click.command()
@click.option("--days", type=click.IntRange(0, 999999), help="0: today since local midnight; N: last N rolling days.")
@click.option("--json", "as_json", is_flag=True, help="Print complete overall and project API responses as JSON.")
@click.option("--verbose", is_flag=True, help="Show token totals and per-project model details.")
@click.option(
    "--exclude-project",
    "excluded_projects",
    multiple=True,
    metavar="PROJECT",
    help="Exclude an exact project ID/path or an unambiguous final directory name.",
)
def main(days: int | None, as_json: bool, verbose: bool, excluded_projects: tuple[str, ...]) -> None:
    """Show OpenCode V2 costs by project and model. Defaults to all time."""
    window = Window.for_days(days, now=time.time())
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    registration = state / "opencode/service.json"
    try:
        connection = Connection.discover(registration)
        with connection.client() as client:
            report = fetch_report(API(client), window, excluded_projects)
    except (APIError, ProjectSelectionError) as error:
        raise click.ClickException(str(error)) from None

    if as_json:
        click.echo(json.dumps(report.json_data(), indent=2, ensure_ascii=False, allow_nan=False))
    else:
        console = Console()
        console.print(render_report(report, window, width=console.width, verbose=verbose))
