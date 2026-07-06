from ocint._errors import OcintError
from ocint.ctx.models import (
    CtxEventContext,
    CtxEventDetail,
    CtxSearchCandidate,
    CtxSession,
    CtxShowRecentSessionsRequest,
    CtxShowSessionRequest,
    CtxShowSessionTranscriptRequest,
    CtxTranscript,
)
from ocint.ctx.show.repository import CtxShowRepository
from ocint.ctx.transcript import snippet_text


def show_session_request(
    repository: CtxShowRepository, request: CtxShowSessionRequest
) -> list[CtxSession] | CtxTranscript:
    match request:
        case CtxShowRecentSessionsRequest(limit=limit):
            return repository.recent_sessions(limit=limit)
        case CtxShowSessionTranscriptRequest(session_id=session_id):
            return show_session_history(repository, session_id)


def show_session_history(repository: CtxShowRepository, session_id: str) -> CtxTranscript:
    session = repository.find_session(session_id)
    if session is None:
        raise OcintError(f"Imported ctx session not found: {session_id}")
    events = repository.session_events(source_id=session.source_id, session_id=session_id)
    ctx_session = CtxSession(
        provider=session.provider,
        session_id=session.session_id,
        parent_id=session.parent_id,
        title=session.title,
        workspace=session.workspace,
        time_created=session.time_created,
        time_updated=session.time_updated,
        event_count=session.event_count,
    )
    return CtxTranscript(
        provider=session.provider, session=ctx_session, events=[_event_detail(event) for event in events]
    )


def show_event_history(repository: CtxShowRepository, event_id: str, *, window: int = 5) -> CtxEventContext:
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
