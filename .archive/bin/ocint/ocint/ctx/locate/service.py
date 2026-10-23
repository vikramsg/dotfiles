from ocint.ctx.locate.repository import CtxLocateRepository
from ocint.ctx.models import CtxLocateResult


def locate_session(repository: CtxLocateRepository, session_id: str) -> CtxLocateResult | None:
    session = repository.find_session(session_id)
    if session is None:
        return None
    return CtxLocateResult(
        provider=session.provider,
        kind="session",
        id=session.session_id,
        db_path=session.source_db_path,
        source_table="session",
        session_id=session.session_id,
    )


def locate_event(repository: CtxLocateRepository, event_id: str) -> CtxLocateResult | None:
    event = repository.find_event(event_id)
    if event is None:
        return None
    return CtxLocateResult(
        provider=event.provider,
        kind="event",
        id=event.event_id,
        db_path=event.source_db_path or repository.db_path,
        source_table=event.source_table,
        session_id=event.session_id,
        source_path=event.source_path,
        citation=event.citation,
    )
