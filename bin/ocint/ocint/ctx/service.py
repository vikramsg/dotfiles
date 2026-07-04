from pathlib import Path

from ocint._errors import OcintError
from ocint.ctx.locate import locate_event, locate_session
from ocint.ctx.models import (
    CtxEventContext,
    CtxEventDetail,
    CtxLocateResult,
    CtxSearchRequest,
    CtxSearchResult,
    CtxSession,
    CtxSource,
    CtxStatus,
    CtxTranscript,
)
from ocint.ctx.search import CtxSearch
from ocint.ctx.transcript import event_text, snippet_text
from ocint.opencode.models import OpenCodeSessionRow, OpenCodeUnifiedEventRow
from ocint.opencode.repository import OpenCodeRepository


class CtxService:
    def __init__(self, repository: OpenCodeRepository) -> None:
        self._repository = repository

    def status(self) -> CtxStatus:
        if not self._repository.db_path.exists():
            return CtxStatus(db_path=self._repository.db_path, db_exists=False)
        sessions = self._repository.sessions()
        return CtxStatus(
            db_path=self._repository.db_path,
            db_exists=True,
            sessions=len(sessions),
            primary_sessions=len([session for session in sessions if session.parent_id is None]),
            events=self._repository.table_count("message") + self._repository.table_count("part") + self._repository.table_count("event"),
        )

    def sources(self) -> list[CtxSource]:
        if not self._repository.db_path.exists():
            return [CtxSource(source_type="sqlite", name="OpenCode DB", path=str(self._repository.db_path), count=0)]
        return [
            CtxSource(source_type="sqlite", name="OpenCode DB", path=str(self._repository.db_path), count=1),
            CtxSource(source_type="table", name="session", count=self._repository.table_count("session")),
            CtxSource(source_type="table", name="message", count=self._repository.table_count("message")),
            CtxSource(source_type="table", name="part", count=self._repository.table_count("part")),
            CtxSource(source_type="table", name="event", count=self._repository.table_count("event")),
        ]

    def search(self, request: CtxSearchRequest) -> list[CtxSearchResult]:
        return CtxSearch(self._repository).search(request)

    def show_session(self, session_id: str) -> CtxTranscript:
        session = self._repository.find_session(session_id)
        if session is None:
            raise OcintError(f"OpenCode session not found: {session_id}")
        events = self._repository.session_events(session_id)
        ctx_session = CtxSession(
            session_id=session.id,
            parent_id=session.parent_id,
            title=session.title,
            workspace=_session_workspace(session),
            time_created=session.time_created,
            time_updated=session.time_updated,
            event_count=len(events),
        )
        return CtxTranscript(session=ctx_session, events=[_event_result(event, session) for event in events])

    def show_event(self, event_id: str, *, window: int = 5) -> CtxEventContext:
        selected = self._repository.find_event(event_id)
        if selected is None:
            raise OcintError(f"OpenCode event not found: {event_id}")
        session = self._repository.find_session(selected.session_id or "")
        if session is None:
            raise OcintError(f"OpenCode session not found for event: {event_id}")
        events = self._repository.session_events(session.id)
        index = next((i for i, event in enumerate(events) if event.id == event_id), 0)
        start = max(0, index - window)
        end = min(len(events), index + window + 1)
        return CtxEventContext(selected=_event_result(selected, session), events=[_event_result(event, session) for event in events[start:end]])

    def locate_session(self, session_id: str) -> CtxLocateResult:
        result = locate_session(self._repository, session_id)
        if result is None:
            raise OcintError(f"OpenCode session not found: {session_id}")
        return result

    def locate_event(self, event_id: str) -> CtxLocateResult:
        result = locate_event(self._repository, event_id)
        if result is None:
            raise OcintError(f"OpenCode event not found: {event_id}")
        return result


def _event_result(event: OpenCodeUnifiedEventRow, session: OpenCodeSessionRow) -> CtxEventDetail:
    text = event_text(event)
    citation = f"opencode session={session.id} event={event.id} table={event.source_table}"
    return CtxEventDetail(
        session_id=session.id,
        event_id=event.id,
        source_table=event.source_table,
        event_type=event.event_type,
        time_created=event.time_created,
        title=session.title,
        workspace=_session_workspace(session),
        source_path=event.source_path,
        snippet=snippet_text(text),
        text=text,
        citation=citation,
        follow_up=f"ocint ctx show event {event.id} --window 5",
    )


def _session_workspace(session: OpenCodeSessionRow) -> str | None:
    return session.cwd or session.data.directory or session.data.workspace or session.data.cwd or session.data.path
