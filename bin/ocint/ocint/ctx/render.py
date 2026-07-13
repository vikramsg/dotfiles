from datetime import UTC, datetime

from ocint._timeutil import format_ms
from ocint.ctx.models import (
    CtxEventContext,
    CtxEventDetail,
    CtxImportResult,
    CtxLocateResult,
    CtxSearchResult,
    CtxSession,
    CtxShowMode,
    CtxSource,
    CtxTranscript,
    CtxTranscriptFormat,
)
from ocint.presentation import Group, Markdown, Presentation, Rule, Table, Text, plain_table

# FIXME: This root module remains a multi-feature renderer; move renderers only as their owning features change.


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


def render_sources(sources: list[CtxSource]) -> str:
    return plain_table(sources)


def render_recent_sessions(sessions: list[CtxSession]) -> str:
    if not sessions:
        return (
            'No imported sessions found.\n\nStart with:\n  ocint ctx search "what you remember"\n  ocint ctx import\n'
        )
    rows = [
        {
            "session_id": session.session_id,
            "updated": format_ms(session.time_updated),
            "events": session.event_count,
            "title": session.title or "",
            "workspace": session.workspace or "",
        }
        for session in sessions
    ]
    return (
        "Recent sessions\n\n"
        f"{plain_table(rows)}\n"
        "\n"
        "Show a session:\n"
        f"  ocint ctx show session {sessions[0].session_id}\n"
        "\n"
        "Search first if you do not know what you need:\n"
        '  ocint ctx search "what you remember"\n'
    )


def render_search_results(results: list[CtxSearchResult], *, verbose: bool = False) -> Presentation:
    if not results:
        return Text("No results")
    blocks: list[Presentation] = []
    for index, result in enumerate(results, start=1):
        content_name, content_style = _search_content_type(result.event_type)
        primary = Table.grid(padding=(0, 2))
        primary.add_column(style="dim", no_wrap=True)
        primary.add_column(overflow="fold")
        primary.add_row("Title", Text(result.title or "Untitled session", style="bold cyan"))
        primary.add_row("Time", _format_search_time(result.time_created))
        primary.add_row("Content type", Text(content_name, style=f"bold {content_style}"))

        metadata = Table.grid(padding=(0, 2))
        metadata.add_column(style="dim", no_wrap=True)
        metadata.add_column(overflow="fold")
        metadata.add_row("Provider", result.provider)
        metadata.add_row("Session ID", result.session_id)
        metadata.add_row("Event ID", result.event_id)
        metadata.add_row("Event type", result.event_type)
        metadata.add_row("Source table", result.source_table)
        if result.workspace:
            metadata.add_row("Workspace", result.workspace)
        if result.source_path:
            metadata.add_row("Path", result.source_path)
        if verbose:
            metadata.add_row("Citation", Text(result.citation, style="dim"))

        result_parts: list[Presentation] = [
            Rule(f"Result {index}", style="cyan"),
            Text(""),
            primary,
            Text(""),
            Text(content_name, style=f"bold {content_style}"),
            Text(""),
            _render_search_content(result),
            Text(""),
            Text("Metadata", style="bold cyan"),
            Text(""),
            metadata,
            Text(""),
        ]
        blocks.append(Group(*result_parts))
    actions = [
        "ocint ctx show event <event-id> --window 5",
        "ocint ctx show session <session-id>",
    ]
    if verbose:
        actions.extend(
            [
                "ocint ctx locate event <event-id>",
                "ocint ctx locate session <session-id>",
            ]
        )
    return Group(*blocks, Rule("Actions", style="cyan"), Text(""), Text("\n".join(actions), style="dim"))


def _format_search_time(value: int | None) -> str:
    if value is None:
        return "Unknown"
    return datetime.fromtimestamp(value / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _render_search_content(result: CtxSearchResult) -> Presentation:
    if result.event_type.lower() in {"text", "assistant", "user", "system", "part"}:
        return Markdown(result.snippet)
    return Text(result.snippet)


def _search_content_type(event_type: str) -> tuple[str, str]:
    match event_type.lower():
        case "tool":
            return "Tool output", "magenta"
        case "file.patch":
            return "Patch", "yellow"
        case "assistant" | "user" | "system" | "text" | "part":
            return "Text", "green"
        case _:
            return "Content", "blue"


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
