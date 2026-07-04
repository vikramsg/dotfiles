from ocint.ctx.models import CtxLocateResult
from ocint.opencode.repository import OpenCodeRepository


def locate_session(repository: OpenCodeRepository, session_id: str) -> CtxLocateResult | None:
    session = repository.find_session(session_id)
    if session is None:
        return None
    return CtxLocateResult(kind="session", id=session.id, db_path=repository.db_path, source_table="session", session_id=session.id)


def locate_event(repository: OpenCodeRepository, event_id: str) -> CtxLocateResult | None:
    event = repository.find_event(event_id)
    if event is None:
        return None
    citation = f"opencode session={event.session_id} event={event.id} table={event.source_table}"
    return CtxLocateResult(
        kind="event",
        id=event.id,
        db_path=repository.db_path,
        source_table=event.source_table,
        session_id=event.session_id,
        source_path=event.source_path,
        citation=citation,
    )
