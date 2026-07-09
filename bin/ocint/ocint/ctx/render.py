import json
from datetime import UTC, datetime
from typing import Any

from ocint._render import render_table
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
    latest_attempt_completed_at = status.latest_attempt_completed_at
    latest_attempt_running_for = ""
    if status.latest_attempt_status == "running" and status.latest_attempt_started_at and status.observed_at_ms:
        latest_attempt_running_for = _duration_between(status.latest_attempt_started_at, status.observed_at_ms)
    latest_attempt_duration = _duration_between(status.latest_attempt_started_at, latest_attempt_completed_at)
    lines = [
        f"PROVIDER: {status.provider}",
        f"CTX_DB: {status.db_path}",
        f"DB_EXISTS: {status.db_exists}",
        f"INDEX_READY: {status.index_ready}",
        f"SESSIONS: {status.sessions}",
        f"PRIMARY_SESSIONS: {status.primary_sessions}",
        f"EVENTS: {status.events}",
        f"SOURCES: {status.sources}",
        "",
        f"SOURCE_DB: {status.source_db_path or ''}",
        f"SOURCE_DB_EXISTS: {status.source_db_exists}",
        "",
        f"REFRESH_LOG: {status.refresh_log_path or ''}",
        f"REFRESH_TTL: {_format_ttl_ms(status.refresh_ttl_ms)}",
        f"REFRESH_FRESHNESS: {status.refresh_freshness}",
        f"REFRESH_IN_PROGRESS: {status.refresh_in_progress}",
        f"REFRESH_SOURCE_ID: {status.refresh_source_id or ''}",
        f"REFRESH_SOURCE: {status.refresh_source_path or ''}",
        f"REFRESH_SOURCES: {len(status.refresh_sources)}",
        "",
        f"LATEST_SUCCESS_STARTED_AT: {format_ms(status.latest_success_started_at)}",
        f"LATEST_SUCCESS_COMPLETED_AT: {format_ms(status.latest_success_completed_at)}",
        f"LATEST_SUCCESS_DURATION: {_duration_between(status.latest_success_started_at, status.latest_success_completed_at)}",
        f"LATEST_ATTEMPT_STARTED_AT: {format_ms(status.latest_attempt_started_at)}",
        f"LATEST_ATTEMPT_COMPLETED_AT: {format_ms(latest_attempt_completed_at)}",
        f"LATEST_ATTEMPT_STATUS: {status.latest_attempt_status or ''}",
        f"LATEST_ATTEMPT_DURATION: {latest_attempt_duration}",
        f"LATEST_ATTEMPT_RUNNING_FOR: {latest_attempt_running_for}",
        f"LATEST_FAILED_AT: {format_ms(status.latest_failed_at)}",
        f"LATEST_ERROR: {status.latest_error_message or ''}",
        "",
        *_checkpoint_lines(status.checkpoint_summary),
        "",
    ]
    return "\n".join(lines)


def _format_duration_ms(value: int | None) -> str:
    if value is None:
        return ""
    total_seconds = max(0, value // 1000)
    days, remainder = divmod(total_seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts[:2])


def _format_ttl_ms(value: int | None) -> str:
    if value is None:
        return ""
    total_seconds = max(0, value // 1000)
    if total_seconds >= 60 and total_seconds % 60 == 0:
        return f"{total_seconds // 60}m"
    return _format_duration_ms(value)


def _duration_between(start_ms: int | None, end_ms: int | None) -> str:
    if start_ms is None or end_ms is None:
        return ""
    return _format_duration_ms(max(0, end_ms - start_ms))


def _checkpoint_lines(checkpoint: str | None) -> list[str]:
    if not checkpoint:
        return ["CHECKPOINT:"]
    try:
        payload = json.loads(checkpoint)
    except json.JSONDecodeError:
        return [f"CHECKPOINT: {checkpoint}"]
    if not isinstance(payload, dict):
        return [f"CHECKPOINT: {checkpoint}"]
    lines = []
    if "events" in payload:
        lines.append(f"CHECKPOINT_EVENTS: {payload['events']}")
    if "sessions" in payload:
        lines.append(f"CHECKPOINT_SESSIONS: {payload['sessions']}")
    if "session_messages" in payload:
        lines.append(f"CHECKPOINT_SESSION_MESSAGES: {payload['session_messages']}")
    if "size" in payload:
        lines.append(f"CHECKPOINT_SOURCE_SIZE: {_format_bytes(payload['size'])}")
    if "mtime_ns" in payload:
        lines.append(f"CHECKPOINT_SOURCE_MTIME: {_format_ns_timestamp(payload['mtime_ns'])}")
    if fingerprint := payload.get("fingerprint"):
        lines.append(f"CHECKPOINT_FINGERPRINT: {_short_fingerprint(fingerprint)}")
    return lines or [f"CHECKPOINT: {checkpoint}"]


def _format_bytes(value: Any) -> str:
    try:
        size = float(value)
    except TypeError, ValueError:
        return str(value)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    unit = units[0]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            break
        size /= 1024
    return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"


def _format_ns_timestamp(value: Any) -> str:
    try:
        timestamp = int(value) / 1_000_000_000
    except TypeError, ValueError:
        return str(value)
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat().replace("+00:00", "Z")


def _short_fingerprint(value: Any) -> str:
    text = str(value)
    if len(text) <= 20:
        return text
    return f"{text[:12]}...{text[-4:]}"


def render_sources(sources: list[CtxSource]) -> str:
    return render_table(sources)


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
        f"{render_table(rows)}\n"
        "\n"
        "Show a session:\n"
        f"  ocint ctx show session {sessions[0].session_id}\n"
        "\n"
        "Search first if you do not know what you need:\n"
        '  ocint ctx search "what you remember"\n'
    )


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
        lines.extend(["", f"    {_search_content_label(result.event_type)}:"])
        lines.extend(f"      {line}" for line in result.snippet.splitlines() or [""])
        lines.extend(["", "    actions:"])
        lines.append(f"      show: {result.follow_up}")
        lines.append(f"      session: ocint ctx show session {result.session_id}")
        if verbose:
            lines.append(f"      citation: {result.citation}")
            lines.append(f"      locate-event: ocint ctx locate event {result.event_id}")
            lines.append(f"      locate-session: ocint ctx locate session {result.session_id}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def _search_content_label(event_type: str) -> str:
    match event_type.lower():
        case "tool":
            return "tool"
        case "file.patch":
            return "patch"
        case "assistant" | "user" | "system" | "text" | "part":
            return "text"
        case _:
            return "content"


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
