import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from ocint._config import resolve_paths
from ocint._models import CliContext, ResolvedPaths
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
    command = click.option(
        "--days",
        type=click.IntRange(min=0),
        help="Include sessions updated in the last N days.",
    )(command)
    return command


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
    app.output.write(
        paths.model_dump_json(indent=2) if output_format == "json" else render_paths(paths), nl=output_format == "json"
    )


@state.command()
@path_options
@click.option("--format", "output_format", type=OutputFormat, default="table", show_default=True)
@click.pass_obj
def schema(app: CliContext, config_path: Path | None, db_path: Path | None, output_format: str) -> None:
    """Inspect SQLite table columns read-only."""
    rows = _with_repository(config_path, db_path, lambda repository: repository.schema())
    app.output.write(render_json(rows, sort_keys=True) if output_format == "json" else render_rows(rows))


@state.command()
@path_options
@window_options
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
    app.output.write(
        result.model_dump_json(indent=2) if output_format == "json" else render_summary(result, window),
        nl=output_format == "json",
    )


@state.command(name="sessions")
@path_options
@window_options
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
    app.output.write(render_json(rows) if output_format == "json" else render_rows(rows))


@state.command()
@path_options
@click.option("--format", "output_format", type=OutputFormat, default="table", show_default=True)
@click.argument("sql")
@click.pass_obj
def query(app: CliContext, config_path: Path | None, db_path: Path | None, output_format: str, sql: str) -> None:
    """Run a single read-only SELECT/WITH query."""
    rows = _with_service(config_path, db_path, lambda service: service.query(sql))
    app.output.write(render_json(rows, sort_keys=True) if output_format == "json" else render_rows(rows))


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
