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
from ocost.window import Window


def fetch_report(api: API, window: Window) -> Report:
    overall = api.stats(window)
    projects = [ProjectUsage(project, api.stats(window, project=project.id)) for project in api.projects()]
    return Report(overall, projects)


@click.command()
@click.option("--days", type=click.IntRange(0, 999999), help="0: today since local midnight; N: last N rolling days.")
@click.option("--json", "as_json", is_flag=True, help="Print complete overall and project API responses as JSON.")
@click.option("--verbose", is_flag=True, help="Show token totals and per-project model details.")
def main(days: int | None, as_json: bool, verbose: bool) -> None:
    """Show OpenCode V2 costs by project and model. Defaults to all time."""
    window = Window.for_days(days, now=time.time())
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    registration = state / "opencode/service.json"
    try:
        connection = Connection.discover(registration)
        with connection.client() as client:
            report = fetch_report(API(client), window)
    except APIError as error:
        raise click.ClickException(str(error)) from None

    if as_json:
        click.echo(json.dumps(report.json_data(), indent=2, ensure_ascii=False, allow_nan=False))
    else:
        console = Console()
        console.print(render_report(report, window, width=console.width, verbose=verbose))
