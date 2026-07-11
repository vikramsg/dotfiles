import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from ocint._config import resolve_paths
from ocint._models import CliContext, ResolvedPaths
from ocint._timeutil import UsageWindow, make_window
from ocint.opencode.repository import OpenCodeRepository
from ocint.presentation import render_json
from ocint.state.render import (
    render_config,
    render_detailed,
    render_query,
    render_schema,
    render_sessions,
    render_summary,
)
from ocint.state.service import StateService

OutputFormat = click.Choice(["table", "json"])


def path_options(command: Callable[..., Any]) -> Callable[..., Any]:
    command = click.option("--db", "db_path", type=click.Path(path_type=Path), help="OpenCode SQLite DB path.")(command)
    command = click.option("--config", "config_path", type=click.Path(path_type=Path), help="OpenCode config path.")(
        command
    )
    return command


def window_options(help_text: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorate(command: Callable[..., Any]) -> Callable[..., Any]:
        return click.option("--days", type=click.IntRange(min=0), help=help_text)(command)

    return decorate


@click.group(name="state")
def state() -> None:
    """Read-only OpenCode SQLite usage and session analytics."""


@state.command()
@path_options
@click.option("--format", "output_format", type=OutputFormat, default="table", show_default=True)
@click.pass_obj
def config(app: CliContext, config_path: Path | None, db_path: Path | None, output_format: str) -> None:
    """Show resolved OpenCode config and DB paths without opening the DB."""
    paths = _resolve_paths(config_path=config_path, db_path=db_path)
    if output_format == "json":
        app.output.write(render_json(paths))
    else:
        app.output.display(render_config(paths))


@state.command()
@path_options
@click.option("--format", "output_format", type=OutputFormat, default="table", show_default=True)
@click.pass_obj
def schema(app: CliContext, config_path: Path | None, db_path: Path | None, output_format: str) -> None:
    """Inspect SQLite table columns read-only."""
    rows = _with_repository(config_path, db_path, lambda repository: repository.schema())
    if output_format == "json":
        app.output.write(render_json(rows, sort_keys=True))
    else:
        app.output.display(render_schema(rows))


@state.command()
@path_options
@window_options("Include sessions updated in the last N days.")
@click.option("--format", "output_format", type=OutputFormat, default="table", show_default=True)
@click.pass_obj
def summary(
    app: CliContext,
    config_path: Path | None,
    db_path: Path | None,
    days: int | None,
    output_format: str,
) -> None:
    """Summarize authoritative token, cost, session, and message usage."""
    window = _window(days=days)
    result = _with_service(config_path, db_path, lambda service: service.summary(window))
    if output_format == "json":
        app.output.write(render_json(result))
    else:
        app.output.display(render_summary(result, window))


@state.command()
@path_options
@window_options("Include assistant messages created in the last N days.")
@click.option("--format", "output_format", type=OutputFormat, default="table", show_default=True)
@click.pass_obj
def detailed(
    app: CliContext,
    config_path: Path | None,
    db_path: Path | None,
    days: int | None,
    output_format: str,
) -> None:
    """Group assistant-message usage by project and historical agent."""
    window = _window(days=days)
    result = _with_service(config_path, db_path, lambda service: service.detailed(window))
    if output_format == "json":
        app.output.write(render_json(result))
    else:
        app.output.display(render_detailed(result, window))


@state.command(name="sessions")
@path_options
@window_options("Include sessions updated in the last N days.")
@click.option("--format", "output_format", type=OutputFormat, default="table", show_default=True)
@click.pass_obj
def sessions_command(
    app: CliContext,
    config_path: Path | None,
    db_path: Path | None,
    days: int | None,
    output_format: str,
) -> None:
    """Group usage by session."""
    window = _window(days=days)
    rows = _with_service(config_path, db_path, lambda service: service.sessions(window))
    if output_format == "json":
        app.output.write(render_json(rows))
    else:
        app.output.display(render_sessions(rows, window))


@state.command()
@path_options
@click.option("--format", "output_format", type=OutputFormat, default="table", show_default=True)
@click.argument("sql")
@click.pass_obj
def query(app: CliContext, config_path: Path | None, db_path: Path | None, output_format: str, sql: str) -> None:
    """Run a single read-only SELECT/WITH query."""
    rows = _with_service(config_path, db_path, lambda service: service.query(sql))
    if output_format == "json":
        app.output.write(render_json(rows, sort_keys=True))
    else:
        app.output.display(render_query(rows))


def _window(*, days: int | None) -> UsageWindow:
    try:
        return make_window(days=days)
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
