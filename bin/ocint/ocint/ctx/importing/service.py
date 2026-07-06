import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol

from ocint.ctx.importing.repository import CtxImportRepository
from ocint.ctx.models import CtxImportEvent, CtxImportProgress, CtxImportRequest, CtxImportResult
from ocint.opencode.models import OpenCodeSessionRow, OpenCodeUnifiedEventRow, payload_paths, payload_to_text

PROVIDER = "opencode"
SOURCE_TYPE = "sqlite"
SOURCE_NAME = "OpenCode DB"


class OpenCodeHistorySource(Protocol):
    """Read-only OpenCode history adapter required by ctx import orchestration."""

    def sessions(self) -> list[OpenCodeSessionRow]: ...

    def all_unified_events(self) -> list[OpenCodeUnifiedEventRow]: ...


def import_history_events(
    request: CtxImportRequest,
    repository: CtxImportRepository,
    source: OpenCodeHistorySource,
) -> Iterator[CtxImportEvent]:
    source_path = request.source_db_path.expanduser()
    yield CtxImportProgress(message="Loading sessions")
    sessions = source.sessions()
    yield CtxImportProgress(message="Loading events")
    events = source.all_unified_events()
    imported_at = int(time.time() * 1000)
    checkpoint = _checkpoint_payload(source_path)
    yield CtxImportProgress(message="Preparing ctx index")
    source_id = repository.upsert_source(
        provider=PROVIDER,
        source_type=SOURCE_TYPE,
        name=SOURCE_NAME,
        source_path=str(source_path),
        imported_at=imported_at,
        sessions=len(sessions),
        events=len(events),
        checkpoint_payload=checkpoint,
    )
    # Rebuild only this source's projection so default imports prune source-deleted
    # history without touching rows imported from other providers or databases.
    repository.clear_source_rows(source_id)
    session_rows = [
        _session_values(source_id=source_id, source_path=source_path, session=session) for session in sessions
    ]
    yield CtxImportProgress(message="Writing sessions", current=0, total=len(sessions))
    sessions_written = repository.upsert_sessions(session_rows)
    yield CtxImportProgress(message="Writing sessions", current=sessions_written, total=len(sessions))
    sessions_by_id = {session.id: session for session in sessions}
    events_written = 0
    files_written = 0
    total_events = len(events)
    for index, event in enumerate(events, start=1):
        values, paths = _event_values(
            source_id=source_id,
            event=event,
            session=sessions_by_id.get(event.session_id or ""),
        )
        repository.upsert_event_with_files(values, paths)
        events_written += 1
        files_written += len(set(paths))
        if _should_report_progress(index, total_events):
            yield CtxImportProgress(message="Writing events", current=index, total=total_events)
    yield CtxImportResult(
        ctx_db_path=repository.db_path,
        source_db_path=source_path,
        sessions_seen=len(sessions),
        sessions_written=sessions_written,
        events_seen=len(events),
        events_written=events_written,
        files_written=files_written,
        checkpoint_updated=True,
    )


def _should_report_progress(current: int, total: int) -> bool:
    return current == 1 or current == total or current % 100 == 0


def _session_values(*, source_id: int, source_path: Path, session: OpenCodeSessionRow) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "provider": PROVIDER,
        "provider_session_id": session.id,
        "session_id": session.id,
        "parent_id": session.parent_id,
        "title": session.title,
        "workspace": _session_workspace(session),
        "time_created": session.time_created,
        "time_updated": session.time_updated,
        "source_path": str(source_path),
        "payload_json": session.data.model_dump_json(by_alias=True, exclude_none=True),
    }


def _event_values(
    *,
    source_id: int,
    event: OpenCodeUnifiedEventRow,
    session: OpenCodeSessionRow | None,
) -> tuple[dict[str, Any], list[str]]:
    paths = payload_paths(event.data)
    if event.source_path and event.source_path not in paths:
        paths.insert(0, event.source_path)
    full_text = payload_to_text(event.data)
    search_text = _search_text(event=event, session=session, full_text=full_text, paths=paths)
    citation = f"opencode session={event.session_id or ''} event={event.id} table={event.source_table}"
    return (
        {
            "source_id": source_id,
            "provider": PROVIDER,
            "provider_session_id": event.session_id,
            "event_id": event.id,
            "source_table": event.source_table,
            "message_id": event.message_id,
            "event_type": event.event_type,
            "time_created": event.time_created,
            "time_updated": event.time_updated,
            "source_path": event.source_path,
            "full_text": full_text,
            "search_text": search_text,
            "payload_json": event.data.model_dump_json(by_alias=True, exclude_none=True),
            "citation": citation,
        },
        paths,
    )


def _search_text(
    *, event: OpenCodeUnifiedEventRow, session: OpenCodeSessionRow | None, full_text: str, paths: list[str]
) -> str:
    session_items: list[str | None] = []
    if session is not None:
        session_items = [
            session.id,
            session.title,
            session.cwd,
            session.data.directory,
            session.data.workspace,
            session.data.cwd,
            session.data.path,
        ]
    event_items = [
        event.id,
        event.event_type,
        event.source_table,
        event.source_path,
        full_text,
        *paths,
    ]
    return " ".join(item for item in [*session_items, *event_items] if item)


def _session_workspace(session: OpenCodeSessionRow) -> str | None:
    return session.cwd or session.data.directory or session.data.workspace or session.data.cwd or session.data.path


def _checkpoint_payload(source_path: Path) -> str:
    stat = source_path.stat()
    return json.dumps({"mtime_ns": stat.st_mtime_ns, "size": stat.st_size}, sort_keys=True)
