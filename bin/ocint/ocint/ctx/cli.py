import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ocint._config import resolve_paths
from ocint._errors import OcintError
from ocint._render import render_csv, render_json, render_raw, render_table
from ocint.ctx.config import CtxBackendConfig, resolve_ctx_backend_config
from ocint.ctx.db import ctx_session, migrate_ctx_db
from ocint.ctx.docs import search_docs, show_doc
from ocint.ctx.duckdb_repository import (
    DuckDBCtxImportRepository,
    DuckDBCtxLocateRepository,
    DuckDBCtxSearchRepository,
    DuckDBCtxShowRepository,
    DuckDBCtxSqlRepository,
    DuckDBCtxStatusRepository,
)
from ocint.ctx.importer import build_import_batch, import_history
from ocint.ctx.locate import locate_event as locate_event_result
from ocint.ctx.locate import locate_session as locate_session_result
from ocint.ctx.models import (
    CtxBenchmarkBackendResult,
    CtxCompareResult,
    CtxImportBatch,
    CtxImportRequest,
    CtxSearchRequest,
    CtxStatus,
)
from ocint.ctx.render import (
    render_compare_result,
    render_event_context,
    render_import_result,
    render_locate,
    render_search_results,
    render_sources,
    render_status,
    render_transcript,
)
from ocint.ctx.repository import (
    CtxImportRepository,
    CtxLocateRepository,
    CtxSearchRepository,
    CtxShowRepository,
    CtxSqlRepository,
    CtxStatusRepository,
)
from ocint.ctx.search import search_history
from ocint.ctx.service import show_event_history, show_session_history
from ocint.ctx.sql import run_ctx_sql


@click.group(name="ctx")
@click.option(
    "--backend",
    type=click.Choice(["sqlite", "duckdb"]),
    help="Ctx index backend. Overrides OCINT_CTX_BACKEND; default is sqlite.",
)
@click.pass_context
def ctx(click_context: click.Context, backend: str | None) -> None:
    """Import, search, and inspect OpenCode local history."""
    click_context.ensure_object(dict)["ctx_backend"] = backend


@ctx.command(name="import")
@click.option("--source-db", type=click.Path(path_type=Path), help="OpenCode SQLite DB to import.")
@click.option("--full", is_flag=True, help="Rebuild rows for this source inside the ocint ctx DB.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def import_command(source_db: Path | None, full: bool, as_json: bool) -> None:
    """Import OpenCode history into the ocint ctx index."""
    result = _import_ctx(source_db=source_db, full=full)
    click.echo(render_json(result) if as_json else render_import_result(result), nl=False)


@ctx.command()
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def status(as_json: bool) -> None:
    """Show imported ctx index availability and counts."""
    config = _ctx_backend_config()
    ctx_db = config.db_path
    source_db = _source_db_path_or_none()
    if not ctx_db.exists():
        result = CtxStatus(
            db_path=ctx_db,
            db_exists=False,
            source_db_path=source_db,
            source_db_exists=source_db.exists() if source_db is not None else False,
        )
    else:
        result = _with_ctx_repository(
            _make_status_repository, lambda repository: repository.status(source_db_path=source_db)
        )
    click.echo(render_json(result) if as_json else render_status(result), nl=False)


@ctx.command()
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def sources(as_json: bool) -> None:
    """List imported ctx history sources."""
    if not _ctx_backend_config().db_path.exists():
        result = []
    else:
        result = _with_ctx_repository(_make_status_repository, lambda repository: repository.sources())
    click.echo(render_json(result) if as_json else render_sources(result), nl=False)


@ctx.command()
@click.argument("query")
@click.option("--session", "session_id", help="Restrict to one native OpenCode session ID.")
@click.option("--workspace", help="Require workspace text to match.")
@click.option("--file", "file_filter", help="Require a file/path match.")
@click.option("--since", help="Only include events since YYYY-MM-DD or a duration like 30d.")
@click.option("--term", "terms", multiple=True, help="Additional required case-insensitive term.")
@click.option("--include-subagents", is_flag=True, help="Include sessions with parent_id set.")
@click.option(
    "--include-current-session",
    is_flag=True,
    help="Accepted compatibility no-op; OpenCode exposes no active session env contract here.",
)
@click.option(
    "--refresh",
    type=click.Choice(["off"]),
    help="Use --refresh off to skip import and search only the existing ctx index.",
)
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
    """Search imported ctx history, importing first when OpenCode is available."""
    _ = include_current_session
    if refresh != "off":
        source_db = _source_db_path_or_none()
        if source_db is not None and source_db.exists():
            _import_ctx(source_db=source_db, full=False)
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
    result = _with_existing_ctx_repository(
        _make_search_repository, lambda repository: search_history(request, repository)
    )
    click.echo(render_json(result) if as_json else render_search_results(result, verbose=verbose), nl=False)


@ctx.group()
def show() -> None:
    """Show imported ctx session transcripts or events."""


@show.command(name="session")
@click.argument("session_id")
@click.option("--mode", type=click.Choice(["lite", "full", "log"]), default="lite", show_default=True)
@click.option(
    "--format", "output_format", type=click.Choice(["text", "markdown", "json"]), default="text", show_default=True
)
@click.option("--out", "out_path", type=click.Path(path_type=Path), help="Write rendered transcript to a file.")
def show_session(session_id: str, mode: str, output_format: str, out_path: Path | None) -> None:
    """Print or write a readable imported session transcript."""
    transcript = _with_existing_ctx_repository(
        _make_show_repository, lambda repository: show_session_history(repository, session_id)
    )
    rendered = (
        render_json(transcript)
        if output_format == "json"
        else render_transcript(transcript, mode=mode, output_format=output_format)
    )
    if out_path is not None:
        out_path.write_text(rendered)
        click.echo(f"Wrote OpenCode session transcript to {out_path}")
        return
    click.echo(rendered, nl=False)


@show.command(name="event")
@click.argument("event_id")
@click.option(
    "--window", type=int, default=5, show_default=True, help="Number of neighboring session events on each side."
)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def show_event(event_id: str, window: int, as_json: bool) -> None:
    """Show an imported event with nearby session context."""
    context = _with_existing_ctx_repository(
        _make_show_repository, lambda repository: show_event_history(repository, event_id, window=window)
    )
    click.echo(render_json(context) if as_json else render_event_context(context), nl=False)


@ctx.group()
def locate() -> None:
    """Locate imported ctx source metadata."""


@locate.command(name="session")
@click.argument("session_id")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def locate_session(session_id: str, as_json: bool) -> None:
    result = _with_existing_ctx_repository(
        _make_locate_repository, lambda repository: locate_session_result(repository, session_id)
    )
    if result is None:
        raise click.ClickException(f"Imported ctx session not found: {session_id}")
    click.echo(render_json(result) if as_json else render_locate(result), nl=False)


@locate.command(name="event")
@click.argument("event_id")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def locate_event(event_id: str, as_json: bool) -> None:
    result = _with_existing_ctx_repository(
        _make_locate_repository, lambda repository: locate_event_result(repository, event_id)
    )
    if result is None:
        raise click.ClickException(f"Imported ctx event not found: {event_id}")
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
@click.option(
    "--format", "output_format", type=click.Choice(["table", "json", "csv", "raw"]), default="table", show_default=True
)
def sql_command(sql: str, output_format: str) -> None:
    """Run a safe read-only query against imported ctx stable views."""
    rows = _with_existing_ctx_repository(_make_sql_repository, lambda repository: run_ctx_sql(repository, sql))
    if output_format == "json":
        rendered = render_json(rows)
    elif output_format == "csv":
        rendered = render_csv(rows)
    elif output_format == "raw":
        rendered = render_raw(rows)
    else:
        rendered = render_table(rows)
    click.echo(rendered, nl=False)


@ctx.command(name="compare")
@click.argument("query")
@click.option("--source-db", type=click.Path(path_type=Path), required=True, help="OpenCode SQLite DB to import once.")
@click.option(
    "--sqlite-db", type=click.Path(path_type=Path), required=True, help="SQLite ctx DB path for this benchmark."
)
@click.option(
    "--duckdb-db", type=click.Path(path_type=Path), required=True, help="DuckDB ctx DB path for this benchmark."
)
@click.option("--limit", type=int, default=50, show_default=True, help="Maximum search results for latency check.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def compare(query: str, source_db: Path, sqlite_db: Path, duckdb_db: Path, limit: int, as_json: bool) -> None:
    """Benchmark SQLite and DuckDB ctx imports/searches against the same source rows."""
    result = _compare_ctx(query=query, source_db=source_db, sqlite_db=sqlite_db, duckdb_db=duckdb_db, limit=limit)
    click.echo(render_json(result) if as_json else render_compare_result(result), nl=False)


def _import_ctx(*, source_db: Path | None, full: bool) -> Any:
    source_path = _source_db_path(source_db)
    config = _ctx_backend_config()
    try:
        migrate_ctx_db(config)
        with ctx_session(config, commit=True) as session:
            repository = _make_import_repository(config, session)
            return import_history(CtxImportRequest(source_db_path=source_path, full=full), repository)
    except (FileNotFoundError, ValueError, OcintError, sqlite3.Error, SQLAlchemyError) as error:
        raise click.ClickException(str(error)) from error


def _compare_ctx(
    *,
    query: str,
    source_db: Path,
    sqlite_db: Path,
    duckdb_db: Path,
    limit: int,
) -> CtxCompareResult:
    source_path = _source_db_path(source_db)
    try:
        transform_start = time.perf_counter()
        batch = build_import_batch(source_path)
        source_transform_ms = _elapsed_ms(transform_start)
        results = [
            _benchmark_backend(
                backend="sqlite",
                db_path=sqlite_db,
                source_path=source_path,
                query=query,
                limit=limit,
                batch=batch,
                source_transform_ms=source_transform_ms,
            ),
            _benchmark_backend(
                backend="duckdb",
                db_path=duckdb_db,
                source_path=source_path,
                query=query,
                limit=limit,
                batch=batch,
                source_transform_ms=source_transform_ms,
            ),
        ]
        return CtxCompareResult(
            query=query,
            source_db_path=source_path,
            results=results,
            speed_ratios=_speed_ratios(results),
        )
    except (FileNotFoundError, ValueError, OcintError, sqlite3.Error, SQLAlchemyError) as error:
        raise click.ClickException(str(error)) from error


def _benchmark_backend(
    *,
    backend: str,
    db_path: Path,
    source_path: Path,
    query: str,
    limit: int,
    batch: CtxImportBatch,
    source_transform_ms: float,
) -> CtxBenchmarkBackendResult:
    config = _compare_backend_config(backend=backend, db_path=db_path)
    migration_start = time.perf_counter()
    migrate_ctx_db(config)
    migration_ms = _elapsed_ms(migration_start)
    with ctx_session(config, commit=True) as session:
        write_result = _make_import_repository(config, session).replace_source_projection(batch)
    request = CtxSearchRequest(query=query, limit=limit)
    search_start = time.perf_counter()
    with ctx_session(config, commit=False) as session:
        search_results = search_history(request, _make_search_repository(config, session))
    search_ms = _elapsed_ms(search_start)
    return CtxBenchmarkBackendResult(
        backend=config.backend,
        db_path=config.db_path,
        source_db_path=source_path,
        sessions_seen=batch.source.sessions,
        sessions_written=write_result.sessions_written,
        events_seen=batch.source.events,
        events_written=write_result.events_written,
        files_written=write_result.files_written,
        migration_ms=migration_ms,
        source_transform_ms=source_transform_ms,
        write_ms=write_result.write_ms,
        fts_ms=write_result.fts_ms,
        total_import_ms=migration_ms + source_transform_ms + write_result.write_ms + write_result.fts_ms,
        search_ms=search_ms,
        search_results=len(search_results),
        index_bytes=_path_size(config.db_path),
    )


def _with_existing_ctx_repository[RepoT](
    repository_factory: Callable[[CtxBackendConfig, Session], RepoT], callback: Callable[[RepoT], Any]
) -> Any:
    config = _ctx_backend_config()
    if not config.db_path.exists():
        raise click.ClickException(f"ocint ctx index does not exist; run `ocint ctx import` first: {config.db_path}")
    return _with_ctx_repository(repository_factory, callback)


def _with_ctx_repository[RepoT](
    repository_factory: Callable[[CtxBackendConfig, Session], RepoT], callback: Callable[[RepoT], Any]
) -> Any:
    config = _ctx_backend_config()
    try:
        with ctx_session(config, commit=False) as session:
            return callback(repository_factory(config, session))
    except (FileNotFoundError, ValueError, OcintError, sqlite3.Error, SQLAlchemyError) as error:
        raise click.ClickException(str(error)) from error


def _ctx_backend_config(*, backend: str | None = None, db_path: Path | None = None) -> CtxBackendConfig:
    try:
        return resolve_ctx_backend_config(backend=backend or _ctx_backend_option(), db_path=db_path)
    except ValueError as error:
        raise click.ClickException(str(error)) from error


def _compare_backend_config(*, backend: str, db_path: Path | None) -> CtxBackendConfig:
    if db_path is None:
        raise click.ClickException(f"ocint ctx compare requires an explicit {backend} benchmark DB path")
    try:
        return resolve_ctx_backend_config(backend=backend, db_path=db_path)
    except ValueError as error:
        raise click.ClickException(str(error)) from error


def _make_import_repository(
    config: CtxBackendConfig, session: Session
) -> CtxImportRepository | DuckDBCtxImportRepository:
    if config.backend == "sqlite":
        return CtxImportRepository(session, db_path=config.db_path)
    return DuckDBCtxImportRepository(session, db_path=config.db_path)


def _make_search_repository(
    config: CtxBackendConfig, session: Session
) -> CtxSearchRepository | DuckDBCtxSearchRepository:
    if config.backend == "sqlite":
        return CtxSearchRepository(session, db_path=config.db_path)
    return DuckDBCtxSearchRepository(session, db_path=config.db_path)


def _make_show_repository(config: CtxBackendConfig, session: Session) -> CtxShowRepository | DuckDBCtxShowRepository:
    if config.backend == "sqlite":
        return CtxShowRepository(session, db_path=config.db_path)
    return DuckDBCtxShowRepository(session, db_path=config.db_path)


def _make_locate_repository(
    config: CtxBackendConfig, session: Session
) -> CtxLocateRepository | DuckDBCtxLocateRepository:
    if config.backend == "sqlite":
        return CtxLocateRepository(session, db_path=config.db_path)
    return DuckDBCtxLocateRepository(session, db_path=config.db_path)


def _make_status_repository(
    config: CtxBackendConfig, session: Session
) -> CtxStatusRepository | DuckDBCtxStatusRepository:
    if config.backend == "sqlite":
        return CtxStatusRepository(session, db_path=config.db_path)
    return DuckDBCtxStatusRepository(session, db_path=config.db_path)


def _make_sql_repository(config: CtxBackendConfig, session: Session) -> CtxSqlRepository | DuckDBCtxSqlRepository:
    if config.backend == "sqlite":
        return CtxSqlRepository(session, db_path=config.db_path)
    return DuckDBCtxSqlRepository(session, db_path=config.db_path)


def _ctx_backend_option() -> str | None:
    context = click.get_current_context(silent=True)
    while context is not None:
        if isinstance(context.obj, dict) and "ctx_backend" in context.obj:
            backend = context.obj["ctx_backend"]
            return str(backend) if backend is not None else None
        context = context.parent
    return None


def _speed_ratios(results: list[CtxBenchmarkBackendResult]) -> dict[str, float | None]:
    by_backend = {result.backend: result for result in results}
    sqlite_result = by_backend.get("sqlite")
    duckdb_result = by_backend.get("duckdb")
    if sqlite_result is None or duckdb_result is None:
        return {}
    ratios: dict[str, float | None] = {}
    for metric in [
        "migration_ms",
        "source_transform_ms",
        "write_ms",
        "fts_ms",
        "total_import_ms",
        "search_ms",
        "index_bytes",
    ]:
        sqlite_value = float(getattr(sqlite_result, metric))
        duckdb_value = float(getattr(duckdb_result, metric))
        ratios[f"sqlite_to_duckdb_{metric}"] = sqlite_value / duckdb_value if duckdb_value else None
    return ratios


def _path_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def _source_db_path(source_db: Path | None = None) -> Path:
    try:
        return resolve_paths(db_path=source_db).db_path if source_db is not None else resolve_paths().db_path
    except ValueError as error:
        raise click.ClickException(str(error)) from error


def _source_db_path_or_none() -> Path | None:
    try:
        return _source_db_path()
    except click.ClickException:
        return None
