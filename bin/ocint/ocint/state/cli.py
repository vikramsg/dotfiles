import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from ocint._config import resolve_paths
from ocint._models import ResolvedPaths
from ocint._render import render_json
from ocint._timeutil import UsageWindow, make_window
from ocint.opencode.repository import OpenCodeRepository
from ocint.state.render import render_paths, render_rows, render_summary
from ocint.state.service import StateService

OutputFormat = click.Choice(["table", "json"])


def path_options(command: Callable[..., Any]) -> Callable[..., Any]:
    command = click.option("--db", "db_path", type=click.Path(path_type=Path), help="OpenCode SQLite DB path.")(command)
    command = click.option("--config", "config_path", type=click.Path(path_type=Path), help="OpenCode config path.")(
        command
    )
    return command


def window_options(command: Callable[..., Any]) -> Callable[..., Any]:
    command = click.option("--until", help="Inclusive UTC end date (YYYY-MM-DD).")(command)
    command = click.option("--since", help="UTC start date (YYYY-MM-DD).")(command)
    command = click.option("--days", type=int, help="Include this many UTC days when --since is omitted.")(command)
    return command


@click.group(name="state")
def state() -> None:
    """Read-only OpenCode SQLite usage and session analytics."""


@state.command()
@path_options
@click.option("--format", "output_format", type=OutputFormat, default="table", show_default=True)
def config(config_path: Path | None, db_path: Path | None, output_format: str) -> None:
    """Show resolved OpenCode config and DB paths without opening the DB."""
    paths = _resolve_paths(config_path=config_path, db_path=db_path)
    click.echo(
        paths.model_dump_json(indent=2) if output_format == "json" else render_paths(paths), nl=output_format == "json"
    )


@state.command()
@path_options
@click.option("--format", "output_format", type=OutputFormat, default="table", show_default=True)
def schema(config_path: Path | None, db_path: Path | None, output_format: str) -> None:
    """Inspect SQLite table columns read-only."""
    rows = _with_repository(config_path, db_path, lambda repository: repository.schema())
    click.echo(render_json(rows, sort_keys=True) if output_format == "json" else render_rows(rows), nl=False)


@state.command()
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
    result = _with_service(config_path, db_path, lambda service: service.summary(window))
    click.echo(
        result.model_dump_json(indent=2) if output_format == "json" else render_summary(result, window),
        nl=output_format == "json",
    )


@state.command(name="daily")
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
    rows = _with_service(config_path, db_path, lambda service: service.daily(window))
    click.echo(render_json(rows) if output_format == "json" else render_rows(rows), nl=False)


@state.command(name="models")
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
    rows = _with_service(config_path, db_path, lambda service: service.models(window))
    click.echo(render_json(rows) if output_format == "json" else render_rows(rows), nl=False)


@state.command(name="sessions")
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
    rows = _with_service(config_path, db_path, lambda service: service.sessions(window))
    click.echo(render_json(rows) if output_format == "json" else render_rows(rows), nl=False)


@state.command()
@path_options
@click.option("--format", "output_format", type=OutputFormat, default="table", show_default=True)
@click.argument("sql")
def query(config_path: Path | None, db_path: Path | None, output_format: str, sql: str) -> None:
    """Run a single read-only SELECT/WITH query."""
    rows = _with_service(config_path, db_path, lambda service: service.query(sql))
    click.echo(render_json(rows, sort_keys=True) if output_format == "json" else render_rows(rows), nl=False)


def _window(*, days: int | None, since: str | None, until: str | None) -> UsageWindow:
    try:
        return make_window(days=days, since=since, until=until)
    except ValueError as error:
        raise click.ClickException(str(error)) from error


def _resolve_paths(*, config_path: Path | None, db_path: Path | None) -> ResolvedPaths:
    try:
        return resolve_paths(config_path=config_path, db_path=db_path)
    except ValueError as error:
        raise click.ClickException(str(error)) from error


def _with_repository(
    config_path: Path | None, db_path: Path | None, callback: Callable[[OpenCodeRepository], Any]
) -> Any:
    paths = _resolve_paths(config_path=config_path, db_path=db_path)
    try:
        return callback(OpenCodeRepository(paths.db_path))
    except (FileNotFoundError, ValueError, sqlite3.Error) as error:
        raise click.ClickException(str(error)) from error


def _with_service(config_path: Path | None, db_path: Path | None, callback: Callable[[StateService], Any]) -> Any:
    return _with_repository(config_path, db_path, lambda repository: callback(StateService(repository)))
