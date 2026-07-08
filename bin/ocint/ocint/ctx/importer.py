import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ocint.ctx.models import CtxImportBatch, CtxImportRequest, CtxImportResult, CtxImportSource
from ocint.ctx.protocols import CtxImportRepositoryProtocol
from ocint.opencode.models import OpenCodeSessionRow, OpenCodeUnifiedEventRow, payload_paths, payload_to_text
from ocint.opencode.repository import OpenCodeRepository

PROVIDER = "opencode"
SOURCE_TYPE = "sqlite"
SOURCE_NAME = "OpenCode DB"


def import_history(request: CtxImportRequest, repository: CtxImportRepositoryProtocol) -> CtxImportResult:
    transform_start = time.perf_counter()
    batch = build_import_batch(request.source_db_path)
    transform_ms = (time.perf_counter() - transform_start) * 1000
    write_result = repository.replace_source_projection(batch)
    return CtxImportResult(
        ctx_db_path=repository.db_path,
        source_db_path=Path(batch.source.source_path),
        sessions_seen=batch.source.sessions,
        sessions_written=write_result.sessions_written,
        events_seen=batch.source.events,
        events_written=write_result.events_written,
        files_written=write_result.files_written,
        checkpoint_updated=True,
        source_transform_ms=transform_ms,
        write_ms=write_result.write_ms,
        fts_ms=write_result.fts_ms,
    )


def build_import_batch(source_db_path: Path) -> CtxImportBatch:
    source_path = source_db_path.expanduser()
    source_repository = OpenCodeRepository(source_path)
    # OpenCodeRepository opens `mode=ro`; import is the only ctx workflow allowed
    # to inspect native OpenCode storage, and it must never mutate that source DB.
    sessions = source_repository.sessions()
    events = source_repository.all_unified_events()
    imported_at = int(time.time() * 1000)
    checkpoint = _checkpoint_payload(source_path)
    source = CtxImportSource(
        source_type=SOURCE_TYPE,
        name=SOURCE_NAME,
        source_path=str(source_path),
        imported_at=imported_at,
        sessions=len(sessions),
        events=len(events),
        checkpoint_payload=checkpoint,
    )
    sessions_by_id = {session.id: session for session in sessions}
    session_rows = [_session_values(source_path=source_path, session=session) for session in sessions]
    event_rows: list[dict[str, Any]] = []
    file_rows: list[dict[str, Any]] = []
    for event in events:
        values, paths = _event_values(
            event=event,
            session=sessions_by_id.get(event.session_id or ""),
        )
        event_rows.append(values)
        file_rows.extend(_file_values(event_values=values, paths=paths))
    return CtxImportBatch(source=source, session_rows=session_rows, event_rows=event_rows, file_rows=file_rows)


def _session_values(*, source_path: Path, session: OpenCodeSessionRow) -> dict[str, Any]:
    return {
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


def _file_values(*, event_values: Mapping[str, Any], paths: list[str]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for path in paths:
        if not path or path in seen:
            continue
        seen.add(path)
        rows.append(
            {
                "provider": event_values["provider"],
                "path": path,
                "provider_session_id": event_values["provider_session_id"],
                "event_id": event_values["event_id"],
                "source_table": event_values["source_table"],
            }
        )
    return rows


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
