from pathlib import Path

from ocint._errors import OcintError
from ocint.ctx.models import (
    CtxEventContext,
    CtxEventDetail,
    CtxSearchCandidate,
    CtxSession,
    CtxSource,
    CtxStatus,
    CtxTranscript,
)
from ocint.ctx.protocols import CtxShowRepositoryProtocol, CtxStatusRepositoryProtocol
from ocint.ctx.transcript import snippet_text


def get_status(repository: CtxStatusRepositoryProtocol, *, source_db_path: Path | None = None) -> CtxStatus:
    return repository.status(source_db_path=source_db_path)


def list_sources(repository: CtxStatusRepositoryProtocol) -> list[CtxSource]:
    return repository.sources()


def show_session_history(repository: CtxShowRepositoryProtocol, session_id: str) -> CtxTranscript:
    session = repository.find_session(session_id)
    if session is None:
        raise OcintError(f"Imported ctx session not found: {session_id}")
    events = repository.session_events(source_id=int(session["source_id"]), session_id=session_id)
    ctx_session = CtxSession(
        provider=str(session["provider"]),
        session_id=str(session["session_id"]),
        parent_id=session["parent_id"],
        title=session["title"],
        workspace=session["workspace"],
        time_created=session["time_created"],
        time_updated=session["time_updated"],
        event_count=int(session["event_count"] or 0),
    )
    return CtxTranscript(
        provider=str(session["provider"]), session=ctx_session, events=[_event_detail(event) for event in events]
    )


def show_event_history(repository: CtxShowRepositoryProtocol, event_id: str, *, window: int = 5) -> CtxEventContext:
    selected = repository.find_event(event_id)
    if selected is None:
        raise OcintError(f"Imported ctx event not found: {event_id}")
    events = repository.event_window(selected, window=window)
    return CtxEventContext(
        provider=selected.provider,
        selected=_event_detail(selected),
        events=[_event_detail(event) for event in events],
    )


def _event_detail(candidate: CtxSearchCandidate) -> CtxEventDetail:
    return CtxEventDetail(
        provider=candidate.provider,
        session_id=candidate.session_id,
        event_id=candidate.event_id,
        source_table=candidate.source_table,
        event_type=candidate.event_type,
        time_created=candidate.time_created,
        title=candidate.title,
        workspace=candidate.workspace,
        source_path=candidate.source_path,
        snippet=snippet_text(candidate.full_text),
        text=candidate.full_text,
        citation=candidate.citation,
        follow_up=f"ocint ctx show event {candidate.event_id} --window 5",
    )
