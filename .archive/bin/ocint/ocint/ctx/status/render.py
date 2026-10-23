import json
from datetime import UTC, datetime
from typing import Any

from structlog.dev import ConsoleRenderer

from ocint._timeutil import format_ms
from ocint.ctx.models import (
    CtxRefreshLogs,
    CtxRefreshLogsUnavailable,
    CtxRefreshRawLogEntry,
    CtxRefreshStructuredLogEntry,
    CtxStatus,
)
from ocint.presentation import Group, Presentation, Text, key_value_section


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


def render_refresh_logs(logs: CtxRefreshLogs) -> Presentation:
    content: list[Presentation] = [Text(str(logs.path), style="bold cyan"), Text("")]
    if isinstance(logs, CtxRefreshLogsUnavailable):
        content.append(Text(logs.message, style="yellow"))
        return Group(*content)
    renderer = ConsoleRenderer(colors=True, sort_keys=False)
    for entry in logs.entries:
        if isinstance(entry, CtxRefreshRawLogEntry):
            content.append(Text(entry.text))
            continue
        if isinstance(entry, CtxRefreshStructuredLogEntry):
            record = json.loads(entry.json_line)
            content.append(Text.from_ansi(renderer(None, "info", record)))
    return Group(*content)


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
