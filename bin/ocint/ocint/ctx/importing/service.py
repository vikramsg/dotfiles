import hashlib
import json
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, Protocol

from ocint.ctx.importing.repository import CtxImportRepository
from ocint.ctx.models import CtxImportEvent, CtxImportProgress, CtxImportRequest, CtxImportResult, CtxRefreshSuccess
from ocint.opencode.models import (
    OpenCodeSessionKey,
    OpenCodeSessionMessageKey,
    OpenCodeSessionRow,
    OpenCodeTranscriptEventKey,
    OpenCodeTranscriptEventRow,
    payload_paths,
    payload_to_text,
)

PROVIDER = "opencode"
SOURCE_TYPE = "sqlite"
SOURCE_NAME = "OpenCode DB"


class OpenCodeHistorySource(Protocol):
    """Read-only OpenCode transcript adapter required by ctx import orchestration."""

    def session_keys(self) -> list[OpenCodeSessionKey]: ...

    def sessions(self) -> list[OpenCodeSessionRow]: ...

    def sessions_for_ids(self, ids: Sequence[str]) -> list[OpenCodeSessionRow]: ...

    def transcript_event_keys(self) -> list[OpenCodeTranscriptEventKey]: ...

    def transcript_event_batches(self, batch_size: int) -> Iterator[list[OpenCodeTranscriptEventRow]]: ...

    def transcript_event_batches_for_keys(
        self,
        keys: Sequence[tuple[str, str]],
        batch_size: int,
    ) -> Iterator[list[OpenCodeTranscriptEventRow]]: ...

    def session_message_keys(self) -> list[OpenCodeSessionMessageKey]: ...

    def source_table_watermarks(self) -> dict[str, dict[str, int | None]]: ...


class CtxRefreshStateWriter(Protocol):
    """Refresh-state persistence used by the shared foreground/background import workflow."""

    def mark_attempt_success(self, source_id: int, success: CtxRefreshSuccess) -> None: ...


def import_history_events(
    request: CtxImportRequest,
    repository: CtxImportRepository,
    refresh_repository: CtxRefreshStateWriter,
    source: OpenCodeHistorySource,
) -> Iterator[CtxImportEvent]:
    source_path = request.source_db_path
    started_at = request.attempt_started_at
    yield CtxImportProgress(message="Preparing ctx index")
    source_id = repository.upsert_source(
        provider=PROVIDER,
        source_type=SOURCE_TYPE,
        name=SOURCE_NAME,
        source_path=str(source_path),
    )

    yield CtxImportProgress(message="Loading sessions")
    session_keys = source.session_keys()
    session_message_keys = source.session_message_keys()
    yield CtxImportProgress(message="Loading events")
    event_keys = source.transcript_event_keys()

    existing_sessions = repository.session_reconciliation_state(source_id)
    first_session_import = not existing_sessions
    changed_session_ids = [key.id for key in session_keys if existing_sessions.get(key.id) != key.fingerprint]
    changed_session_id_set = set(changed_session_ids)
    source_session_ids = {key.id for key in session_keys}
    deleted_session_ids = set(existing_sessions) - source_session_ids
    # Deleted source sessions are pruned later; reproject their still-present
    # events first so denormalized title/workspace search terms are removed.
    projection_affected_session_ids = changed_session_id_set | deleted_session_ids
    session_fingerprint_by_id = {key.id: key.fingerprint for key in session_keys}
    sessions = (
        source.sessions()
        if len(changed_session_ids) == len(session_keys)
        else source.sessions_for_ids(changed_session_ids)
    )
    session_rows = [
        _session_values(
            source_id=source_id,
            source_path=source_path,
            session=session,
            source_fingerprint=session_fingerprint_by_id[session.id],
        )
        for session in sessions
    ]
    yield CtxImportProgress(message="Writing sessions", current=0, total=len(changed_session_ids))
    sessions_written = (
        repository.insert_sessions(session_rows) if first_session_import else repository.upsert_sessions(session_rows)
    )
    yield CtxImportProgress(message="Writing sessions", current=sessions_written, total=len(changed_session_ids))

    existing_events = repository.event_reconciliation_state(source_id)
    first_event_import = not existing_events
    changed_event_key_models = [
        key for key in event_keys if _event_requires_projection(key, existing_events, projection_affected_session_ids)
    ]
    changed_event_keys = [(key.source_table, key.id) for key in changed_event_key_models]
    event_session_ids = sorted({key.session_id for key in changed_event_key_models if key.session_id})
    sessions_by_id = {session.id: session for session in source.sessions_for_ids(event_session_ids)}

    events_written = 0
    files_written = 0
    batch_size = 5_000
    event_fingerprints = {(key.source_table, key.id): key.fingerprint for key in event_keys}
    next_event_pk = repository.next_event_pk() if first_event_import else None
    event_batches = (
        source.transcript_event_batches(batch_size)
        if len(changed_event_keys) == len(event_keys)
        else source.transcript_event_batches_for_keys(changed_event_keys, batch_size)
    )
    for batch in event_batches:
        rows = []
        for event in batch:
            source_fingerprint = event_fingerprints.get((event.source_table, event.id))
            if source_fingerprint is None:
                continue
            rows.append(
                _event_values(
                    source_id=source_id,
                    event=event,
                    session=sessions_by_id.get(event.session_id or ""),
                    source_fingerprint=source_fingerprint,
                )
            )
        if next_event_pk is not None:
            for values, _paths in rows:
                values["id"] = next_event_pk
                next_event_pk += 1
        batch_events_written, batch_files_written = (
            repository.insert_events_with_files(rows)
            if first_event_import
            else repository.upsert_events_with_files(rows)
        )
        events_written += batch_events_written
        files_written += batch_files_written
        yield CtxImportProgress(message="Writing events", current=events_written, total=len(changed_event_keys))

    if not changed_event_keys:
        yield CtxImportProgress(message="Writing events", current=0, total=0)

    seen_event_keys = [(key.source_table, key.id) for key in event_keys]
    repository.prune_events_not_seen(source_id=source_id, seen_keys=seen_event_keys)
    repository.prune_sessions_not_seen(source_id=source_id, seen_session_ids=[key.id for key in session_keys])

    final_sessions = repository.count_sessions(source_id)
    final_events = repository.count_events(source_id)
    repository.update_source_counts(source_id=source_id, sessions=final_sessions, events=final_events)
    completed_at = _now_ms()
    refresh_repository.mark_attempt_success(
        source_id,
        CtxRefreshSuccess(
            started_at=started_at,
            completed_at=completed_at,
            checkpoint_payload=_checkpoint_payload(source_path, session_keys, event_keys, session_message_keys),
            source_watermark_payload=_watermark_payload(source, session_message_keys),
        ),
    )
    yield CtxImportResult(
        ctx_db_path=repository.db_path,
        source_db_path=source_path,
        sessions_seen=len(session_keys),
        sessions_written=sessions_written,
        events_seen=len(event_keys),
        events_written=events_written,
        files_written=files_written,
        checkpoint_updated=True,
    )


def _event_requires_projection(
    key: OpenCodeTranscriptEventKey,
    existing_events: dict[tuple[str, str], dict[str, str | None]],
    projection_affected_session_ids: set[str],
) -> bool:
    existing = existing_events.get((key.source_table, key.id))
    if existing is None:
        return True
    if existing["source_fingerprint"] != key.fingerprint:
        return True
    if existing["provider_session_id"] != key.session_id:
        return True
    if existing["message_id"] != key.message_id:
        return True
    return key.session_id in projection_affected_session_ids if key.session_id is not None else False


def _session_values(
    *,
    source_id: int,
    source_path: Path,
    session: OpenCodeSessionRow,
    source_fingerprint: str,
) -> dict[str, Any]:
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
        "source_fingerprint": source_fingerprint,
    }


def _event_values(
    *,
    source_id: int,
    event: OpenCodeTranscriptEventRow,
    session: OpenCodeSessionRow | None,
    source_fingerprint: str,
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
            "source_fingerprint": source_fingerprint,
        },
        paths,
    )


def _search_text(
    *, event: OpenCodeTranscriptEventRow, session: OpenCodeSessionRow | None, full_text: str, paths: list[str]
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


def _checkpoint_payload(
    source_path: Path,
    session_keys: Sequence[OpenCodeSessionKey],
    event_keys: Sequence[OpenCodeTranscriptEventKey],
    session_message_keys: Sequence[OpenCodeSessionMessageKey],
) -> str:
    stat = source_path.stat()
    return json.dumps(
        {
            "mtime_ns": stat.st_mtime_ns,
            "size": stat.st_size,
            "sessions": len(session_keys),
            "events": len(event_keys),
            "session_messages": len(session_message_keys),
            "fingerprint": _keys_fingerprint(session_keys, event_keys, session_message_keys),
        },
        sort_keys=True,
    )


def _watermark_payload(
    source: OpenCodeHistorySource,
    session_message_keys: Sequence[OpenCodeSessionMessageKey],
) -> str:
    return json.dumps(
        {
            "tables": source.source_table_watermarks(),
            "session_message_fingerprint": _session_message_fingerprint(session_message_keys),
        },
        sort_keys=True,
    )


def _keys_fingerprint(
    session_keys: Sequence[OpenCodeSessionKey],
    event_keys: Sequence[OpenCodeTranscriptEventKey],
    session_message_keys: Sequence[OpenCodeSessionMessageKey],
) -> str:
    payload = {
        "sessions": [key.model_dump(mode="json") for key in session_keys],
        "events": [key.model_dump(mode="json") for key in event_keys],
        "session_messages": [key.model_dump(mode="json") for key in session_message_keys],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _session_message_fingerprint(session_message_keys: Sequence[OpenCodeSessionMessageKey]) -> str:
    payload = [key.model_dump(mode="json") for key in session_message_keys]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _now_ms() -> int:
    return int(time.time() * 1000)
