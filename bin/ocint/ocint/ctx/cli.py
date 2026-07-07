import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import click
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ocint._config import resolve_paths
from ocint._errors import OcintError
from ocint._models import CliContext
from ocint._render import render_csv, render_json, render_raw, render_table
from ocint.ctx.config import resolve_ctx_db_path, resolve_ctx_refresh_config
from ocint.ctx.db import ctx_session, current_ctx_head_revision, migrate_ctx_db
from ocint.ctx.docs import render_doc_topics, search_docs, show_doc
from ocint.ctx.importing import CtxImportRepository, import_history_events
from ocint.ctx.importing.service import PROVIDER, SOURCE_NAME, SOURCE_TYPE
from ocint.ctx.locate import CtxLocateRepository
from ocint.ctx.locate import locate_event as locate_event_result
from ocint.ctx.locate import locate_session as locate_session_result
from ocint.ctx.models import (
    CtxImportProgress,
    CtxImportRequest,
    CtxImportResult,
    CtxRefreshAction,
    CtxRefreshConfig,
    CtxRefreshDecision,
    CtxRefreshFailure,
    CtxRefreshPolicyInput,
    CtxRefreshState,
    CtxSearchRequest,
    CtxSearchResult,
    CtxShowMode,
    CtxShowRecentSessionsRequest,
    CtxShowSessionTranscriptRequest,
    CtxSqlOutputFormat,
    CtxTranscriptFormat,
    RefreshMode,
)
from ocint.ctx.refresh import (
    CtxRefreshRepository,
    acquire_refresh_lock,
    decide_refresh_action,
    refresh_lock_in_progress,
    schedule_refresh_worker,
)
from ocint.ctx.render import (
    render_event_context,
    render_import_result,
    render_locate,
    render_recent_sessions,
    render_search_results,
    render_sources,
    render_status,
    render_transcript,
)
from ocint.ctx.search import CtxSearchRepository, search_history
from ocint.ctx.show import CtxShowRepository, show_event_history, show_session_request
from ocint.ctx.sql import CtxSqlRepository, run_ctx_sql
from ocint.ctx.sql.models import CtxSqlConfig, default_ctx_sql_config
from ocint.ctx.status import CtxStatusRepository, get_status, list_sources, require_ctx_index_ready
from ocint.opencode.repository import OpenCodeRepository


@click.group(
    name="ctx",
    help="""Import, search, and inspect OpenCode local history.

First use:

  ocint ctx search "what you remember"

  ocint ctx show session

  ocint ctx docs show
""",
)
def ctx() -> None:
    pass


@ctx.command(name="import")
@click.option("--source-db", type=click.Path(path_type=Path), help="OpenCode SQLite DB to import.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
@click.pass_obj
def import_command(app: CliContext, source_db: Path | None, as_json: bool) -> None:
    """Import OpenCode history into the ocint ctx index."""
    result = _consume_import_events(app, source_db=source_db, progress_enabled=not as_json)
    app.output.write(render_json(result) if as_json else render_import_result(result))


@ctx.command(name="refresh-worker", hidden=True)
def refresh_worker() -> None:
    """Hidden detached refresh entrypoint used by stale-while-revalidate search."""
    _run_refresh_worker()


@ctx.command()
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
@click.pass_obj
def status(app: CliContext, as_json: bool) -> None:
    """Show imported ctx index availability and counts."""
    ctx_db = _ctx_db_path()
    refresh_config = _ctx_refresh_config(ctx_db)
    in_progress = refresh_lock_in_progress(refresh_config.lock_path)
    with _ready_ctx_session(
        expected_errors=(FileNotFoundError, ValueError, OcintError, sqlite3.Error, SQLAlchemyError),
    ) as (session, ctx_db, sql_config, expected_revision):
        repository = CtxStatusRepository(session, db_path=ctx_db)
        refresh_repository = CtxRefreshRepository(session, db_path=ctx_db)
        result = get_status(
            repository,
            sql_config,
            expected_revision,
            refresh_config=refresh_config,
            refresh_state=refresh_repository.aggregate_state(),
            refresh_in_progress=in_progress,
            now_ms=_now_ms(),
        )
    app.output.write(render_json(result) if as_json else render_status(result))


@ctx.command()
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
@click.pass_obj
def sources(app: CliContext, as_json: bool) -> None:
    """List imported ctx history sources."""
    with _ready_ctx_session(
        expected_errors=(FileNotFoundError, ValueError, OcintError, sqlite3.Error, SQLAlchemyError),
    ) as (session, ctx_db, sql_config, expected_revision):
        repository = CtxStatusRepository(session, db_path=ctx_db)
        result = list_sources(repository, sql_config, expected_revision)
    app.output.write(render_json(result) if as_json else render_sources(result))


@ctx.command(
    help="""Search imported ctx history.

Default search uses auto refresh. Missing or unready indexes refresh before search;
ready stale indexes search first and refresh in the background:

  ocint ctx search "native event marker"

Use --refresh off for deterministic index-only search; it never imports:

  ocint ctx search "native event marker" --refresh off
"""
)
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
    help="Include the active OpenCode session tree when OPENCODE_SESSION_ID is set.",
)
@click.option(
    "--refresh",
    type=click.Choice([RefreshMode.AUTO.value, RefreshMode.OFF.value]),
    help="Refresh mode: auto (default stale-while-revalidate) or off (index-only).",
)
@click.option("--limit", type=int, default=50, show_default=True, help="Maximum number of results to print.")
@click.option("--verbose", is_flag=True, help="Show citations and copyable follow-up commands.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
@click.pass_obj
def search(
    app: CliContext,
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
    """Search imported ctx history using typed refresh orchestration at the CLI boundary."""
    mode = _refresh_mode(refresh)
    ctx_db = _ctx_db_path()
    request = CtxSearchRequest(
        query=query,
        session_id=session_id,
        workspace=workspace,
        file=file_filter,
        since=since,
        terms=list(terms),
        include_subagents=include_subagents,
        active_session_id=_active_opencode_session_id(),
        include_current_session=include_current_session,
        limit=limit,
    )
    background_source_db: Path | None = None
    background_refresh_config: CtxRefreshConfig | None = None
    match mode:
        case RefreshMode.OFF:
            result = _search_ready_index(request, query=query)
            app.output.write(render_json(result) if as_json else render_search_results(result, verbose=verbose))
            return
        case RefreshMode.AUTO:
            refresh_config = _ctx_refresh_config(ctx_db)
            source_db = _source_db_path()
            decision = _auto_refresh_decision(ctx_db=ctx_db, refresh_config=refresh_config)
            match decision.action:
                case CtxRefreshAction.FOREGROUND_REFRESH:
                    _consume_import_events(app, source_db=source_db, progress_enabled=not as_json)
                    result = _search_ready_index(request, query=query)
                case CtxRefreshAction.SEARCH_ONLY:
                    result = _search_ready_index(request, query=query)
                case CtxRefreshAction.SEARCH_THEN_BACKGROUND_REFRESH:
                    result = _search_ready_index(request, query=query)
                    background_source_db = source_db
                    background_refresh_config = refresh_config
    app.output.write(render_json(result) if as_json else render_search_results(result, verbose=verbose))
    if background_source_db is not None and background_refresh_config is not None:
        _schedule_refresh_after_search(
            app,
            ctx_db=ctx_db,
            source_db=background_source_db,
            refresh_config=background_refresh_config,
            verbose=verbose,
            as_json=as_json,
        )


def _search_ready_index(request: CtxSearchRequest, *, query: str) -> list[CtxSearchResult]:
    with _ready_ctx_session(
        expected_errors=(FileNotFoundError, ValueError, OcintError, sqlite3.Error, SQLAlchemyError),
        recovery_hint=f'Run `ocint ctx search "{query}"` without `--refresh off`, or run `ocint ctx import`.',
    ) as (session, ctx_db, _sql_config, _expected_revision):
        repository = CtxSearchRepository(session, db_path=ctx_db)
        return search_history(request, repository)


@ctx.group(
    help="""Show imported ctx session transcripts or events.

Discover sessions without already knowing IDs:

  ocint ctx show session

Then inspect one session:

  ocint ctx show session <session-id>
"""
)
def show() -> None:
    pass


@show.command(
    name="session",
    help="""List recent sessions or render one session transcript.

Without SESSION_ID, lists recent sessions:

  ocint ctx show session

With SESSION_ID, shows that transcript:

  ocint ctx show session <session-id>

  ocint ctx show session <session-id> --mode full
""",
)
@click.argument("session_id", required=False, metavar="[SESSION_ID]")
@click.option(
    "--mode",
    type=click.Choice([mode.value for mode in CtxShowMode]),
    default=CtxShowMode.LITE.value,
    show_default=True,
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice([output.value for output in CtxTranscriptFormat]),
    default=CtxTranscriptFormat.TEXT.value,
    show_default=True,
)
@click.option("--out", "out_path", type=click.Path(path_type=Path), help="Write rendered transcript to a file.")
@click.pass_obj
def show_session(app: CliContext, session_id: str | None, mode: str, output_format: str, out_path: Path | None) -> None:
    """Print or write a readable imported session transcript."""
    show_mode = _show_mode(mode)
    transcript_format = _transcript_format(output_format)
    request = _show_session_request(session_id)
    with _ready_ctx_session(
        expected_errors=(FileNotFoundError, ValueError, OcintError, sqlite3.Error, SQLAlchemyError),
    ) as (session, ctx_db, _sql_config, _expected_revision):
        repository = CtxShowRepository(session, db_path=ctx_db)
        result = show_session_request(repository, request)
    if isinstance(result, list):
        rendered = (
            render_json(result) if transcript_format == CtxTranscriptFormat.JSON else render_recent_sessions(result)
        )
    else:
        match transcript_format:
            case CtxTranscriptFormat.JSON:
                rendered = render_json(result)
            case CtxTranscriptFormat.TEXT | CtxTranscriptFormat.MARKDOWN:
                rendered = render_transcript(result, mode=show_mode, output_format=transcript_format)
    if out_path is not None:
        out_path.write_text(rendered)
        app.output.write(f"Wrote OpenCode session transcript to {out_path}\n")
        return
    app.output.write(rendered)


@show.command(name="event")
@click.argument("event_id")
@click.option(
    "--window", type=int, default=5, show_default=True, help="Number of neighboring session events on each side."
)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
@click.pass_obj
def show_event(app: CliContext, event_id: str, window: int, as_json: bool) -> None:
    """Show an imported event with nearby session context."""
    with _ready_ctx_session(
        expected_errors=(FileNotFoundError, ValueError, OcintError, sqlite3.Error, SQLAlchemyError),
    ) as (session, ctx_db, _sql_config, _expected_revision):
        repository = CtxShowRepository(session, db_path=ctx_db)
        context = show_event_history(repository, event_id, window=window)
    app.output.write(render_json(context) if as_json else render_event_context(context))


@ctx.group()
def locate() -> None:
    """Locate imported ctx source metadata."""


@locate.command(name="session")
@click.argument("session_id")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
@click.pass_obj
def locate_session(app: CliContext, session_id: str, as_json: bool) -> None:
    with _ready_ctx_session(
        expected_errors=(FileNotFoundError, ValueError, OcintError, sqlite3.Error, SQLAlchemyError),
    ) as (session, ctx_db, _sql_config, _expected_revision):
        repository = CtxLocateRepository(session, db_path=ctx_db)
        result = locate_session_result(repository, session_id)
    if result is None:
        raise click.ClickException(f"Imported ctx session not found: {session_id}")
    app.output.write(render_json(result) if as_json else render_locate(result))


@locate.command(name="event")
@click.argument("event_id")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
@click.pass_obj
def locate_event(app: CliContext, event_id: str, as_json: bool) -> None:
    with _ready_ctx_session(
        expected_errors=(FileNotFoundError, ValueError, OcintError, sqlite3.Error, SQLAlchemyError),
    ) as (session, ctx_db, _sql_config, _expected_revision):
        repository = CtxLocateRepository(session, db_path=ctx_db)
        result = locate_event_result(repository, event_id)
    if result is None:
        raise click.ClickException(f"Imported ctx event not found: {event_id}")
    app.output.write(render_json(result) if as_json else render_locate(result))


@ctx.group(
    help="""Show embedded ocint ctx documentation.

List topics:

  ocint ctx docs show

Show one topic:

  ocint ctx docs show quickstart
"""
)
def docs() -> None:
    pass


@docs.command(
    name="show",
    help="""Show a docs topic, or list topics when TOPIC is omitted.

Available topics: quickstart, commands, discovery, refresh, sql

Examples:

  ocint ctx docs show

  ocint ctx docs show quickstart
""",
)
@click.argument("topic", required=False, metavar="[TOPIC]")
@click.pass_obj
def docs_show(app: CliContext, topic: str | None) -> None:
    try:
        app.output.write(render_doc_topics() if topic is None else show_doc(topic))
    except ValueError as error:
        raise click.ClickException(str(error)) from error


@docs.command(name="search")
@click.argument("query")
@click.pass_obj
def docs_search(app: CliContext, query: str) -> None:
    matches = search_docs(query)
    app.output.write("\n\n".join(matches) + ("\n" if matches else "No docs results\n"))


@ctx.command(name="sql")
@click.argument("sql")
@click.option(
    "--format",
    "output_format",
    type=click.Choice([output.value for output in CtxSqlOutputFormat]),
    default=CtxSqlOutputFormat.TABLE.value,
    show_default=True,
)
@click.pass_obj
def sql_command(app: CliContext, sql: str, output_format: str) -> None:
    """Run a safe read-only query against imported ctx stable views."""
    with _ready_ctx_session(
        expected_errors=(FileNotFoundError, ValueError, OcintError, sqlite3.Error, SQLAlchemyError),
    ) as (session, ctx_db, sql_config, _expected_revision):
        repository = CtxSqlRepository(session, db_path=ctx_db)
        rows = run_ctx_sql(repository, sql, sql_config)
    match _sql_output_format(output_format):
        case CtxSqlOutputFormat.JSON:
            rendered = render_json(rows)
        case CtxSqlOutputFormat.CSV:
            rendered = render_csv(rows)
        case CtxSqlOutputFormat.RAW:
            rendered = render_raw(rows)
        case CtxSqlOutputFormat.TABLE:
            rendered = render_table(rows)
    app.output.write(rendered)


def _auto_refresh_decision(*, ctx_db: Path, refresh_config: CtxRefreshConfig) -> CtxRefreshDecision:
    index_ready, refresh_state = _ctx_index_ready_state(ctx_db)
    return decide_refresh_action(
        CtxRefreshPolicyInput(
            mode=RefreshMode.AUTO,
            ttl_ms=refresh_config.ttl_ms,
            index_ready=index_ready,
            source_state=refresh_state,
            now_ms=_now_ms(),
        )
    )


def _ctx_index_ready_state(ctx_db: Path) -> tuple[bool, CtxRefreshState | None]:
    if not ctx_db.exists():
        return False, None
    try:
        sql_config, expected_revision = _ctx_readiness_contract()
        with ctx_session(ctx_db, commit=False) as session:
            status_repository = CtxStatusRepository(session, db_path=ctx_db)
            if not status_repository.index_ready(sql_config, expected_revision):
                return False, None
            refresh_repository = CtxRefreshRepository(session, db_path=ctx_db)
            return True, refresh_repository.aggregate_state()
    except FileNotFoundError, ValueError, OcintError, sqlite3.Error, SQLAlchemyError:
        return False, None


def _schedule_refresh_after_search(
    app: CliContext,
    *,
    ctx_db: Path,
    source_db: Path,
    refresh_config: CtxRefreshConfig,
    verbose: bool,
    as_json: bool,
) -> None:
    try:
        pid = schedule_refresh_worker(ctx_db_path=ctx_db, source_db_path=source_db, log_path=refresh_config.log_path)
    except OSError as error:
        app.output.write(
            f"ctx refresh scheduling failed: {error}\n",
            stderr=True,
            enabled=verbose and not as_json,
        )
        return
    app.output.write(
        f"ctx refresh scheduled in background (pid {pid}); log: {refresh_config.log_path}\n",
        stderr=True,
        enabled=verbose and not as_json,
    )


def _consume_import_events(app: CliContext, *, source_db: Path | None, progress_enabled: bool) -> CtxImportResult:
    result: CtxImportResult | None = None
    with app.output.progress("Importing OpenCode history into ocint ctx index", enabled=progress_enabled) as progress:
        for event in _import_ctx_events(source_db=source_db):
            match event:
                case CtxImportProgress():
                    progress.update(event.message, current=event.current, total=event.total)
                case CtxImportResult():
                    result = event
                    progress.update(
                        "Imported OpenCode history",
                        current=event.events_written,
                        total=event.events_seen,
                    )
    if result is None:
        raise click.ClickException("ctx import did not produce a result")
    return result


def _import_ctx_events(*, source_db: Path | None) -> Iterator[CtxImportProgress | CtxImportResult]:
    source_path = _source_db_path(source_db)
    ctx_db = _ctx_db_path()
    refresh_config = _ctx_refresh_config(ctx_db)
    try:
        _reject_ctx_source_alias(ctx_db=ctx_db, source_path=source_path)
    except ValueError as error:
        raise click.ClickException(str(error)) from error
    try:
        migrate_ctx_db(ctx_db)
        with acquire_refresh_lock(refresh_config.lock_path, blocking=False) as lock:
            if not lock.acquired:
                raise click.ClickException(
                    f"ocint ctx refresh is already running for {ctx_db}; try again after it completes"
                )
            yield from _run_unlocked_import(ctx_db=ctx_db, source_path=source_path)
    except click.ClickException:
        raise
    except (FileNotFoundError, ValueError, OcintError, sqlite3.Error, SQLAlchemyError) as error:
        _record_refresh_failure(ctx_db=ctx_db, source_path=source_path, error=error)
        raise click.ClickException(str(error)) from error


def _run_unlocked_import(*, ctx_db: Path, source_path: Path) -> Iterator[CtxImportProgress | CtxImportResult]:
    with ctx_session(ctx_db, commit=True) as session:
        repository = CtxImportRepository(session, db_path=ctx_db)
        refresh_repository = CtxRefreshRepository(session, db_path=ctx_db)
        source = OpenCodeRepository(source_path)
        yield from import_history_events(
            CtxImportRequest(source_db_path=source_path),
            repository,
            refresh_repository,
            source,
        )


def _run_refresh_worker() -> None:
    source_path = _source_db_path()
    ctx_db = _ctx_db_path()
    refresh_config = _ctx_refresh_config(ctx_db)
    _reject_ctx_source_alias(ctx_db=ctx_db, source_path=source_path)
    try:
        migrate_ctx_db(ctx_db)
        with acquire_refresh_lock(refresh_config.lock_path, blocking=False) as lock:
            if not lock.acquired:
                return
            for _event in _run_unlocked_import(ctx_db=ctx_db, source_path=source_path):
                pass
    except (FileNotFoundError, ValueError, OcintError, sqlite3.Error, SQLAlchemyError) as error:
        _record_refresh_failure(ctx_db=ctx_db, source_path=source_path, error=error)
        raise click.ClickException(str(error)) from error


def _record_refresh_failure(*, ctx_db: Path, source_path: Path, error: BaseException) -> None:
    try:
        migrate_ctx_db(ctx_db)
        with ctx_session(ctx_db, commit=True) as session:
            import_repository = CtxImportRepository(session, db_path=ctx_db)
            refresh_repository = CtxRefreshRepository(session, db_path=ctx_db)
            source_id = import_repository.upsert_source(
                provider=PROVIDER,
                source_type=SOURCE_TYPE,
                name=SOURCE_NAME,
                source_path=str(source_path.expanduser()),
            )
            refresh_repository.mark_attempt_failed(
                source_id,
                CtxRefreshFailure(attempted_at=_now_ms(), error_message=_error_message(error)),
            )
    except FileNotFoundError, ValueError, OcintError, sqlite3.Error, SQLAlchemyError:
        return


def _error_message(error: BaseException) -> str:
    message = str(error)
    if len(message) <= 1_000:
        return message
    return f"{message[:997]}..."


def _reject_ctx_source_alias(*, ctx_db: Path, source_path: Path) -> None:
    """Protect the read-only OpenCode source DB before ctx migrations run."""
    ctx_resolved = ctx_db.expanduser().resolve(strict=False)
    source_resolved = source_path.expanduser().resolve(strict=False)

    aliases = ctx_resolved == source_resolved
    if not aliases and ctx_db.exists() and source_path.exists():
        aliases = ctx_db.samefile(source_path)

    if aliases:
        raise ValueError("ocint ctx DB must not be the same file as the OpenCode source DB")


def _ctx_db_path() -> Path:
    try:
        return resolve_ctx_db_path()
    except ValueError as error:
        raise click.ClickException(str(error)) from error


def _ctx_refresh_config(ctx_db: Path) -> CtxRefreshConfig:
    try:
        return resolve_ctx_refresh_config(ctx_db_path=ctx_db)
    except ValueError as error:
        raise click.ClickException(str(error)) from error


def _now_ms() -> int:
    return int(time.time() * 1000)


def _require_existing_ctx_db_path(*, recovery_hint: str | None = None) -> Path:
    ctx_db = _ctx_db_path()
    if not ctx_db.exists():
        message = f"ocint ctx index does not exist; run `ocint ctx import` first: {ctx_db}"
        if recovery_hint is not None:
            message = f"{message}\n{recovery_hint}"
        raise click.ClickException(message)
    return ctx_db


def _ctx_readiness_contract() -> tuple[CtxSqlConfig, str]:
    return default_ctx_sql_config(), current_ctx_head_revision()


@contextmanager
def _ready_ctx_session(
    *,
    expected_errors: tuple[type[BaseException], ...],
    recovery_hint: str | None = None,
) -> Iterator[tuple[Session, Path, CtxSqlConfig, str]]:
    ctx_db = _require_existing_ctx_db_path(recovery_hint=recovery_hint)
    try:
        sql_config, expected_revision = _ctx_readiness_contract()
        with ctx_session(ctx_db, commit=False) as session:
            _require_ready_ctx_index(session, ctx_db, sql_config, expected_revision)
            yield session, ctx_db, sql_config, expected_revision
    except expected_errors as error:
        message = str(error)
        if recovery_hint is not None and "run `ocint ctx import` first" in message:
            message = f"{message}\n{recovery_hint}"
        raise click.ClickException(message) from error


def _require_ready_ctx_index(session: Session, ctx_db: Path, config: CtxSqlConfig, expected_revision: str) -> None:
    """Enforce migrated ctx objects before feature repositories read persisted rows."""
    repository = CtxStatusRepository(session, db_path=ctx_db)
    require_ctx_index_ready(repository, config, expected_revision)


def _show_session_request(session_id: str | None) -> CtxShowRecentSessionsRequest | CtxShowSessionTranscriptRequest:
    match session_id:
        case None:
            return CtxShowRecentSessionsRequest(limit=10)
        case value:
            return CtxShowSessionTranscriptRequest(session_id=value)


def _active_opencode_session_id() -> str | None:
    """Return the active OpenCode session ID exposed to ctx CLI commands."""
    session_id = os.environ.get("OPENCODE_SESSION_ID", "").strip()
    return session_id or None


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


def _refresh_mode(value: str | None) -> RefreshMode:
    if value is None:
        return RefreshMode.AUTO
    try:
        return RefreshMode(value)
    except ValueError as error:
        raise click.ClickException(str(error)) from error


def _show_mode(value: str) -> CtxShowMode:
    try:
        return CtxShowMode(value)
    except ValueError as error:
        raise click.ClickException(str(error)) from error


def _transcript_format(value: str) -> CtxTranscriptFormat:
    try:
        return CtxTranscriptFormat(value)
    except ValueError as error:
        raise click.ClickException(str(error)) from error


def _sql_output_format(value: str) -> CtxSqlOutputFormat:
    try:
        return CtxSqlOutputFormat(value)
    except ValueError as error:
        raise click.ClickException(str(error)) from error
