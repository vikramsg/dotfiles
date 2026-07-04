from pathlib import Path

from ocint.ctx.models import CtxLocateResult
from ocint.ctx.repository import CtxLocateRepository


def locate_session(repository: CtxLocateRepository, session_id: str) -> CtxLocateResult | None:
    session = repository.find_session(session_id)
    if session is None:
        return None
    return CtxLocateResult(
        provider=str(session["provider"]),
        kind="session",
        id=str(session["session_id"]),
        db_path=Path(str(session["source_db_path"])),
        source_table="session",
        session_id=str(session["session_id"]),
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
