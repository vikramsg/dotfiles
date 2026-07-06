from ocint._render import render_table
from ocint._timeutil import format_ms
from ocint.ctx.models import (
    CtxEventContext,
    CtxEventDetail,
    CtxImportResult,
    CtxLocateResult,
    CtxSearchResult,
    CtxShowMode,
    CtxSource,
    CtxStatus,
    CtxTranscript,
    CtxTranscriptFormat,
)


def render_import_result(result: CtxImportResult) -> str:
    return "\n".join(
        [
            f"PROVIDER: {result.provider}",
            f"CTX_DB: {result.ctx_db_path}",
            f"SOURCE_DB: {result.source_db_path}",
            f"SESSIONS_SEEN: {result.sessions_seen}",
            f"SESSIONS_WRITTEN: {result.sessions_written}",
            f"EVENTS_SEEN: {result.events_seen}",
            f"EVENTS_WRITTEN: {result.events_written}",
            f"FILES_WRITTEN: {result.files_written}",
            f"CHECKPOINT_UPDATED: {result.checkpoint_updated}",
            "",
        ]
    )


def render_status(status: CtxStatus) -> str:
    return "\n".join(
        [
            f"PROVIDER: {status.provider}",
            f"DB: {status.db_path}",
            f"DB_EXISTS: {status.db_exists}",
            f"INDEX_READY: {status.index_ready}",
            f"SESSIONS: {status.sessions}",
            f"PRIMARY_SESSIONS: {status.primary_sessions}",
            f"EVENTS: {status.events}",
            f"SOURCES: {status.sources}",
            f"SOURCE_DB: {status.source_db_path or ''}",
            f"SOURCE_DB_EXISTS: {status.source_db_exists}",
            "",
        ]
    )


def render_sources(sources: list[CtxSource]) -> str:
    return render_table(sources)


def render_search_results(results: list[CtxSearchResult], *, verbose: bool = False) -> str:
    if not results:
        return "No results\n"
    blocks = []
    for index, result in enumerate(results, start=1):
        lines = [
            f"[{index}] {result.provider} session={result.session_id} event={result.event_id} table={result.source_table} type={result.event_type}",
            f"    time={format_ms(result.time_created)} title={result.title or ''}",
        ]
        if result.source_path:
            lines.append(f"    path={result.source_path}")
        lines.append(f"    {result.snippet}")
        lines.append(f"    show: {result.follow_up}")
        lines.append(f"    session: ocint ctx show session {result.session_id}")
        if verbose:
            lines.append(f"    citation: {result.citation}")
            lines.append(f"    locate-event: ocint ctx locate event {result.event_id}")
            lines.append(f"    locate-session: ocint ctx locate session {result.session_id}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def render_transcript(
    transcript: CtxTranscript,
    *,
    mode: CtxShowMode = CtxShowMode.LITE,
    output_format: CtxTranscriptFormat = CtxTranscriptFormat.TEXT,
) -> str:
    match output_format:
        case CtxTranscriptFormat.MARKDOWN:
            return _render_transcript_markdown(transcript, mode=mode)
        case CtxTranscriptFormat.JSON:
            raise ValueError("JSON transcripts are rendered by the CLI JSON renderer")
        case CtxTranscriptFormat.TEXT:
            pass
    lines = [
        f"PROVIDER: {transcript.provider}",
        f"SESSION: {transcript.session.session_id}",
        f"TITLE: {transcript.session.title or ''}",
        f"WORKSPACE: {transcript.session.workspace or ''}",
        f"EVENTS: {transcript.session.event_count}",
        "",
    ]
    for event in transcript.events:
        match mode:
            case CtxShowMode.LOG:
                lines.append(
                    f"{format_ms(event.time_created)}\t{event.source_table}\t{event.event_id}\t{event.event_type}\t{event.snippet}"
                )
            case CtxShowMode.LITE | CtxShowMode.FULL:
                lines.append(
                    f"[{event.source_table}:{event.event_id}] {event.event_type} {format_ms(event.time_created)}"
                )
                lines.append(_transcript_event_content(event, mode=mode))
                lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_event_context(context: CtxEventContext) -> str:
    lines = [f"SELECTED: {context.selected.citation}", ""]
    for event in context.events:
        marker = "*" if event.event_id == context.selected.event_id else " "
        lines.append(
            f"{marker} [{event.source_table}:{event.event_id}] {event.event_type} {format_ms(event.time_created)}"
        )
        content = event.text if event.event_id == context.selected.event_id else event.snippet
        lines.append(f"  {content}")
    return "\n".join(lines) + "\n"


def render_locate(result: CtxLocateResult) -> str:
    lines = [
        f"PROVIDER: {result.provider}",
        f"KIND: {result.kind}",
        f"ID: {result.id}",
        f"DB: {result.db_path}",
        f"SOURCE_TABLE: {result.source_table or ''}",
        f"SESSION_ID: {result.session_id or ''}",
        f"SOURCE_PATH: {result.source_path or ''}",
    ]
    if result.citation:
        lines.append(f"CITATION: {result.citation}")
    lines.append("")
    return "\n".join(lines)


def _render_transcript_markdown(transcript: CtxTranscript, *, mode: CtxShowMode) -> str:
    lines = [
        f"# OpenCode session {transcript.session.session_id}",
        "",
        f"- Provider: {transcript.provider}",
        f"- Title: {transcript.session.title or ''}",
        f"- Workspace: {transcript.session.workspace or ''}",
        f"- Events: {transcript.session.event_count}",
        "",
    ]
    for event in transcript.events:
        lines.append(f"## {event.source_table}:{event.event_id}")
        lines.append("")
        lines.append(f"- Type: {event.event_type}")
        lines.append(f"- Time: {format_ms(event.time_created)}")
        lines.append(f"- Citation: `{event.citation}`")
        lines.append("")
        match mode:
            case CtxShowMode.FULL:
                lines.append(f"{event.text}\n\nFollow-up: `{event.follow_up}`")
            case CtxShowMode.LITE | CtxShowMode.LOG:
                lines.append(event.snippet)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _transcript_event_content(event: CtxEventDetail, *, mode: CtxShowMode) -> str:
    match mode:
        case CtxShowMode.FULL:
            return f"{event.text}\n{event.citation}"
        case CtxShowMode.LITE | CtxShowMode.LOG:
            return event.snippet
