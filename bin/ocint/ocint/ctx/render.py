import json
from datetime import UTC, datetime
from typing import Any

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
from ocint.presentation import Group, Markdown, Presentation, Rule, Table, Text, key_value_section, plain_table


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


def render_status(status: CtxStatus) -> Presentation:
    latest_attempt_completed_at = status.latest_attempt_completed_at
    latest_attempt_running_for = ""
    if status.latest_attempt_status == "running" and status.latest_attempt_started_at and status.observed_at_ms:
        latest_attempt_running_for = _duration_between(status.latest_attempt_started_at, status.observed_at_ms)
    latest_attempt_duration = _duration_between(status.latest_attempt_started_at, latest_attempt_completed_at)
    summary = [
        (
            "Usable",
            f"{'yes' if status.db_exists and status.index_ready else 'no'} — "
            f"{'index is ready' if status.index_ready else 'index is not ready'}",
        ),
        ("Index freshness", status.refresh_freshness),
        ("Configured source", _configured_source_summary(status)),
        ("Refresh", _refresh_summary(status)),
        ("Last success", format_ms(status.latest_success_completed_at) or "never"),
    ]
    source_groups: list[Presentation] = []
    for index, source in enumerate(status.refresh_sources, start=1):
        source_groups.append(
            key_value_section(
                f"Refresh source {index}: {source.name}",
                [
                    ("SOURCE_ID", source.source_id),
                    ("PROVIDER", source.provider),
                    ("SOURCE_TYPE", source.source_type),
                    ("NAME", source.name),
                    ("SOURCE_PATH", source.source_path),
                    ("REFRESH_FRESHNESS", source.refresh_freshness),
                    ("LATEST_ATTEMPT_STARTED_AT", format_ms(source.latest_attempt_started_at)),
                    ("LATEST_ATTEMPT_COMPLETED_AT", format_ms(source.latest_attempt_completed_at)),
                    ("LATEST_ATTEMPT_STATUS", source.latest_attempt_status),
                    ("LATEST_SUCCESS_STARTED_AT", format_ms(source.latest_success_started_at)),
                    ("LATEST_SUCCESS_COMPLETED_AT", format_ms(source.latest_success_completed_at)),
                    ("LATEST_SUCCESS_CHECKPOINT_PAYLOAD", source.latest_success_checkpoint_payload),
                    ("SOURCE_WATERMARK_PAYLOAD", source.source_watermark_payload),
                    ("LATEST_FAILED_AT", format_ms(source.latest_failed_at)),
                    ("LATEST_ERROR_MESSAGE", source.latest_error_message),
                    ("CHECKPOINT_SUMMARY", source.checkpoint_summary),
                ],
            )
        )
    return Group(
        Text("Context index status", style="bold"),
        key_value_section("Summary", summary),
        key_value_section(
            "Index",
            [
                ("PROVIDER", status.provider),
                ("CTX_DB", status.db_path),
                ("DB_EXISTS", status.db_exists),
                ("INDEX_READY", status.index_ready),
                ("SESSIONS", status.sessions),
                ("PRIMARY_SESSIONS", status.primary_sessions),
                ("EVENTS", status.events),
                ("SOURCES", status.sources),
                ("OBSERVED_AT", format_ms(status.observed_at_ms)),
            ],
        ),
        key_value_section(
            "Configured source",
            [("SOURCE_DB", status.source_db_path), ("SOURCE_DB_EXISTS", status.source_db_exists)],
        ),
        key_value_section(
            "Refresh",
            [
                ("REFRESH_LOG", status.refresh_log_path),
                ("REFRESH_TTL", _format_ttl_ms(status.refresh_ttl_ms)),
                ("REFRESH_FRESHNESS", status.refresh_freshness),
                ("REFRESH_IN_PROGRESS", status.refresh_in_progress),
                ("REFRESH_SOURCE_ID", status.refresh_source_id),
                ("REFRESH_SOURCE_PROVIDER", status.refresh_source_provider),
                ("REFRESH_SOURCE_TYPE", status.refresh_source_type),
                ("REFRESH_SOURCE_NAME", status.refresh_source_name),
                ("REFRESH_SOURCE", status.refresh_source_path),
                ("REFRESH_SOURCES", len(status.refresh_sources)),
            ],
        ),
        key_value_section(
            "Attempts, success, and failure",
            [
                ("LATEST_SUCCESS_STARTED_AT", format_ms(status.latest_success_started_at)),
                ("LATEST_SUCCESS_COMPLETED_AT", format_ms(status.latest_success_completed_at)),
                (
                    "LATEST_SUCCESS_DURATION",
                    _duration_between(status.latest_success_started_at, status.latest_success_completed_at),
                ),
                ("LATEST_ATTEMPT_STARTED_AT", format_ms(status.latest_attempt_started_at)),
                ("LATEST_ATTEMPT_COMPLETED_AT", format_ms(latest_attempt_completed_at)),
                ("LATEST_ATTEMPT_STATUS", status.latest_attempt_status),
                ("LATEST_ATTEMPT_DURATION", latest_attempt_duration),
                ("LATEST_ATTEMPT_RUNNING_FOR", latest_attempt_running_for),
                ("LATEST_FAILED_AT", format_ms(status.latest_failed_at)),
                ("LATEST_ERROR", status.latest_error_message),
            ],
        ),
        key_value_section(
            "Checkpoint",
            [("CHECKPOINT_SUMMARY", status.checkpoint_summary), *_checkpoint_rows(status.checkpoint_summary)],
        ),
        key_value_section("Refresh sources", [("COUNT", len(status.refresh_sources))]),
        *source_groups,
    )


def _configured_source_summary(status: CtxStatus) -> str:
    if status.source_db_path is None:
        return "unknown — no source is configured"
    if not status.source_db_exists:
        return "missing — configured source does not exist"
    if status.refresh_source_path is None or str(status.source_db_path) != status.refresh_source_path:
        return "different — configured source does not match the selected indexed source"
    if status.refresh_freshness == "fresh":
        return "current — configured source matches the fresh indexed source"
    if status.refresh_freshness == "stale":
        return "stale — configured source matches, but its index is stale"
    return "unknown — configured source matches, but freshness is unknown"


def _checkpoint_rows(checkpoint: str | None) -> list[tuple[str, object]]:
    rows = []
    for line in _checkpoint_lines(checkpoint):
        label, separator, value = line.partition(":")
        rows.append((label, value.lstrip() if separator else ""))
    return rows


def _refresh_summary(status: CtxStatus) -> str:
    if status.refresh_in_progress or status.latest_attempt_status == "running":
        return "running"
    failed_is_current = status.latest_attempt_status == "failed" and (
        status.latest_success_completed_at is None
        or status.latest_attempt_started_at is None
        or status.latest_attempt_started_at >= status.latest_success_completed_at
    )
    if failed_is_current:
        return f"failed — {status.latest_error_message or 'latest attempt failed'}"
    return "idle"


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
