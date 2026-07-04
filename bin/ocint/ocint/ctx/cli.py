import sqlite3
from pathlib import Path
from typing import Any, Callable

import click

from ocint._config import resolve_paths
from ocint._errors import OcintError
from ocint._render import render_csv, render_json, render_raw, render_table
from ocint.ctx.docs import search_docs, show_doc
from ocint.ctx.models import CtxSearchRequest
from ocint.ctx.render import render_event_context, render_locate, render_search_results, render_sources, render_status, render_transcript
from ocint.ctx.service import CtxService
from ocint.ctx.sql import run_ctx_sql
from ocint.opencode.repository import OpenCodeRepository


@click.group(name="ctx")
def ctx() -> None:
    """Search and inspect OpenCode local history only."""


@ctx.command()
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def status(as_json: bool) -> None:
    """Show OpenCode history availability and counts."""
    result = _with_service(lambda service: service.status(), allow_missing=True)
    click.echo(render_json(result) if as_json else render_status(result), nl=False)


@ctx.command()
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def sources(as_json: bool) -> None:
    """List OpenCode history sources."""
    result = _with_service(lambda service: service.sources(), allow_missing=True)
    click.echo(render_json(result) if as_json else render_sources(result), nl=False)


@ctx.command()
@click.argument("query")
@click.option("--session", "session_id", help="Restrict to one native OpenCode session ID.")
@click.option("--workspace", help="Require workspace text to match.")
@click.option("--file", "file_filter", help="Require a file/path match.")
@click.option("--since", help="Only include events since YYYY-MM-DD or a duration like 30d.")
@click.option("--term", "terms", multiple=True, help="Additional required case-insensitive term.")
@click.option("--include-subagents", is_flag=True, help="Include sessions with parent_id set.")
@click.option("--include-current-session", is_flag=True, help="Accepted compatibility no-op; OpenCode exposes no active session env contract here.")
@click.option("--refresh", type=click.Choice(["off"]), help="Accepted compatibility no-op; ocint has no persistent ctx index.")
@click.option("--limit", type=int, default=50, show_default=True, help="Maximum number of results to print.")
@click.option("--verbose", is_flag=True, help="Show citations and copyable follow-up commands.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def search(
    query: str,
    session_id: str | None,
    workspace: str | None,
    file_filter: str | None,
    since: str | None,
    terms: tuple[str, ...],
    include_subagents: bool,
    include_current_session: bool,
    refresh: str | None,
    limit: int,
    verbose: bool,
    as_json: bool,
) -> None:
    """Search OpenCode local history on demand."""
    _ = (include_current_session, refresh)
    request = CtxSearchRequest(
        query=query,
        session_id=session_id,
        workspace=workspace,
        file=file_filter,
        since=since,
        terms=list(terms),
        include_subagents=include_subagents,
        limit=limit,
    )
    result = _with_service(lambda service: service.search(request))
    click.echo(render_json(result) if as_json else render_search_results(result, verbose=verbose), nl=False)


@ctx.group()
def show() -> None:
    """Show OpenCode session transcripts or events."""


@show.command(name="session")
@click.argument("session_id")
@click.option("--mode", type=click.Choice(["lite", "full", "log"]), default="lite", show_default=True)
@click.option("--format", "output_format", type=click.Choice(["text", "markdown", "json"]), default="text", show_default=True)
@click.option("--out", "out_path", type=click.Path(path_type=Path), help="Write rendered transcript to a file.")
def show_session(session_id: str, mode: str, output_format: str, out_path: Path | None) -> None:
    """Print or write a readable OpenCode session transcript."""
    transcript = _with_service(lambda service: service.show_session(session_id))
    rendered = render_json(transcript) if output_format == "json" else render_transcript(transcript, mode=mode, output_format=output_format)
    if out_path is not None:
        out_path.write_text(rendered)
        click.echo(f"Wrote OpenCode session transcript to {out_path}")
        return
    click.echo(rendered, nl=False)


@show.command(name="event")
@click.argument("event_id")
@click.option("--window", type=int, default=5, show_default=True, help="Number of neighboring session events on each side.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def show_event(event_id: str, window: int, as_json: bool) -> None:
    """Show an OpenCode event with nearby session context."""
    context = _with_service(lambda service: service.show_event(event_id, window=window))
    click.echo(render_json(context) if as_json else render_event_context(context), nl=False)


@ctx.group()
def locate() -> None:
    """Locate native OpenCode source metadata."""


@locate.command(name="session")
@click.argument("session_id")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def locate_session(session_id: str, as_json: bool) -> None:
    result = _with_service(lambda service: service.locate_session(session_id))
    click.echo(render_json(result) if as_json else render_locate(result), nl=False)


@locate.command(name="event")
@click.argument("event_id")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def locate_event(event_id: str, as_json: bool) -> None:
    result = _with_service(lambda service: service.locate_event(event_id))
    click.echo(render_json(result) if as_json else render_locate(result), nl=False)


@ctx.group()
def docs() -> None:
    """Show embedded ocint ctx documentation."""


@docs.command(name="show")
@click.argument("topic")
def docs_show(topic: str) -> None:
    try:
        click.echo(show_doc(topic), nl=False)
    except ValueError as error:
        raise click.ClickException(str(error)) from error


@docs.command(name="search")
@click.argument("query")
def docs_search(query: str) -> None:
    matches = search_docs(query)
    click.echo("\n\n".join(matches) + ("\n" if matches else "No docs results\n"), nl=False)


@ctx.command(name="sql")
@click.argument("sql")
@click.option("--format", "output_format", type=click.Choice(["table", "json", "csv", "raw"]), default="table", show_default=True)
def sql_command(sql: str, output_format: str) -> None:
    """Run a safe read-only query against temporary ctx views."""
    rows = _with_repository(lambda repository: run_ctx_sql(repository, sql))
    if output_format == "json":
        rendered = render_json(rows)
    elif output_format == "csv":
        rendered = render_csv(rows)
    elif output_format == "raw":
        rendered = render_raw(rows)
    else:
        rendered = render_table(rows)
    click.echo(rendered, nl=False)


def _repository() -> OpenCodeRepository:
    try:
        paths = resolve_paths()
    except ValueError as error:
        raise click.ClickException(str(error)) from error
    return OpenCodeRepository(paths.db_path)


def _with_repository(callback: Callable[[OpenCodeRepository], Any], *, allow_missing: bool = False) -> Any:
    repository = _repository()
    if allow_missing and not repository.db_path.exists():
        return callback(repository)
    try:
        return callback(repository)
    except (FileNotFoundError, ValueError, OcintError, sqlite3.Error) as error:
        raise click.ClickException(str(error)) from error


def _with_service(callback: Callable[[CtxService], Any], *, allow_missing: bool = False) -> Any:
    return _with_repository(lambda repository: callback(CtxService(repository)), allow_missing=allow_missing)
