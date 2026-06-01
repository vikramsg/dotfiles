import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click
from pydantic import TypeAdapter

from opencode_state.config import resolve_paths
from opencode_state.db import inspect_schema, open_readonly_connection, run_select_query
from opencode_state.models import DailyUsage, ModelUsage, ResolvedPaths, SessionUsage
from opencode_state.render import render_paths, render_rows, render_summary
from opencode_state.stats import daily_usage, make_window, model_usage, session_usage, summarize_usage


OutputFormat = click.Choice(["table", "json"])
DAILY_USAGE_LIST = TypeAdapter(list[DailyUsage])
MODEL_USAGE_LIST = TypeAdapter(list[ModelUsage])
SESSION_USAGE_LIST = TypeAdapter(list[SessionUsage])


def path_options(command: Callable[..., Any]) -> Callable[..., Any]:
    command = click.option("--db", "db_path", type=click.Path(path_type=Path), help="OpenCode SQLite DB path.")(command)
    command = click.option("--config", "config_path", type=click.Path(path_type=Path), help="OpenCode config path.")(command)
    return command


def window_options(command: Callable[..., Any]) -> Callable[..., Any]:
    command = click.option("--until", help="Inclusive UTC end date (YYYY-MM-DD).")(command)
    command = click.option("--since", help="UTC start date (YYYY-MM-DD).")(command)
    command = click.option("--days", type=int, help="Include this many UTC days when --since is omitted.")(command)
    return command


@click.group()
def main() -> None:
    """Read-only OpenCode SQLite usage and session analytics."""


@main.command()
@path_options
@click.option("--format", "output_format", type=OutputFormat, default="table", show_default=True)
def config(config_path: Path | None, db_path: Path | None, output_format: str) -> None:
    """Show resolved OpenCode config and DB paths without opening the DB."""
    paths = _resolve_paths(config_path=config_path, db_path=db_path)
    if output_format == "json":
        click.echo(paths.model_dump_json(indent=2))
    else:
        click.echo(render_paths(paths), nl=False)


@main.command()
@path_options
@click.option("--format", "output_format", type=OutputFormat, default="table", show_default=True)
def schema(config_path: Path | None, db_path: Path | None, output_format: str) -> None:
    """Inspect SQLite table columns read-only."""
    rows = _with_connection(config_path, db_path, lambda con, _paths: inspect_schema(con))
    if output_format == "json":
        click.echo(json.dumps(rows, indent=2, sort_keys=True))
    else:
        click.echo(render_rows(rows), nl=False)


@main.command()
@path_options
@window_options
@click.option("--format", "output_format", type=OutputFormat, default="table", show_default=True)
def summary(
    config_path: Path | None,
    db_path: Path | None,
    days: int | None,
    since: str | None,
    until: str | None,
    output_format: str,
) -> None:
    """Summarize token, cost, session, and LLM step usage."""
    window = _window(days=days, since=since, until=until)
    result = _with_connection(
        config_path,
        db_path,
        lambda con, paths: summarize_usage(con, db_path=paths.db_path, window=window),
    )
    if output_format == "json":
        click.echo(result.model_dump_json(indent=2))
    else:
        click.echo(render_summary(result, window), nl=False)


@main.command(name="daily")
@path_options
@window_options
@click.option("--format", "output_format", type=OutputFormat, default="table", show_default=True)
def daily_command(
    config_path: Path | None,
    db_path: Path | None,
    days: int | None,
    since: str | None,
    until: str | None,
    output_format: str,
) -> None:
    """Group usage by UTC day."""
    window = _window(days=days, since=since, until=until)
    rows = _with_connection(config_path, db_path, lambda con, _paths: daily_usage(con, window=window))
    if output_format == "json":
        click.echo(DAILY_USAGE_LIST.dump_json(rows, indent=2).decode())
    else:
        click.echo(render_rows(rows), nl=False)


@main.command(name="models")
@path_options
@window_options
@click.option("--format", "output_format", type=OutputFormat, default="table", show_default=True)
def models_command(
    config_path: Path | None,
    db_path: Path | None,
    days: int | None,
    since: str | None,
    until: str | None,
    output_format: str,
) -> None:
    """Group usage by model."""
    window = _window(days=days, since=since, until=until)
    rows = _with_connection(config_path, db_path, lambda con, _paths: model_usage(con, window=window))
    if output_format == "json":
        click.echo(MODEL_USAGE_LIST.dump_json(rows, indent=2).decode())
    else:
        click.echo(render_rows(rows), nl=False)


@main.command(name="sessions")
@path_options
@window_options
@click.option("--format", "output_format", type=OutputFormat, default="table", show_default=True)
def sessions_command(
    config_path: Path | None,
    db_path: Path | None,
    days: int | None,
    since: str | None,
    until: str | None,
    output_format: str,
) -> None:
    """Group usage by session."""
    window = _window(days=days, since=since, until=until)
    rows = _with_connection(config_path, db_path, lambda con, _paths: session_usage(con, window=window))
    if output_format == "json":
        click.echo(SESSION_USAGE_LIST.dump_json(rows, indent=2).decode())
    else:
        click.echo(render_rows(rows), nl=False)


@main.command()
@path_options
@click.option("--format", "output_format", type=OutputFormat, default="table", show_default=True)
@click.argument("sql")
def query(config_path: Path | None, db_path: Path | None, output_format: str, sql: str) -> None:
    """Run a single read-only SELECT/WITH query."""
    rows = _with_connection(config_path, db_path, lambda con, _paths: run_select_query(con, sql))
    if output_format == "json":
        click.echo(json.dumps(rows, indent=2, sort_keys=True))
    else:
        click.echo(render_rows(rows), nl=False)


def _window(*, days: int | None, since: str | None, until: str | None):
    try:
        return make_window(days=days, since=since, until=until)
    except ValueError as error:
        raise click.ClickException(str(error)) from error


def _resolve_paths(*, config_path: Path | None, db_path: Path | None) -> ResolvedPaths:
    try:
        return resolve_paths(config_path=config_path, db_path=db_path)
    except ValueError as error:
        raise click.ClickException(str(error)) from error


def _with_connection(config_path: Path | None, db_path: Path | None, callback: Callable[..., Any]) -> Any:
    paths = _resolve_paths(config_path=config_path, db_path=db_path)
    try:
        with open_readonly_connection(paths.db_path) as connection:
            return callback(connection, paths)
    except (FileNotFoundError, ValueError, sqlite3.Error) as error:
        raise click.ClickException(str(error)) from error


if __name__ == "__main__":
    main()
