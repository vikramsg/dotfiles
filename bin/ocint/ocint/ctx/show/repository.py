from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import Session

from ocint.ctx.db.schema import ctx_event, ctx_session
from ocint.ctx.history import (
    CandidateOrder,
    candidate_query_sql,
    candidate_rows,
    session_summary_sql,
)
from ocint.ctx.models import CtxSearchCandidate, CtxSession, CtxSessionSummary


class CtxShowRepository:
    def __init__(self, session: Session, *, db_path: Path) -> None:
        self._session = session
        self.db_path = db_path

    def find_event(self, event_id: str) -> CtxSearchCandidate | None:
        candidates = _candidate_query(self._session, "e.event_id = :event_id", {"event_id": event_id}, limit=1)
        return candidates[0] if candidates else None

    def find_session(self, session_id: str) -> CtxSessionSummary | None:
        return _find_session(self._session, session_id)

    def recent_sessions(self, *, limit: int) -> list[CtxSession]:
        statement = (
            select(
                ctx_session.c.provider,
                ctx_session.c.provider_session_id.label("session_id"),
                ctx_session.c.parent_id,
                ctx_session.c.title,
                ctx_session.c.workspace,
                ctx_session.c.time_created,
                ctx_session.c.time_updated,
                func.count(ctx_event.c.id).label("event_count"),
            )
            .select_from(
                ctx_session.outerjoin(
                    ctx_event,
                    and_(
                        ctx_event.c.source_id == ctx_session.c.source_id,
                        ctx_event.c.provider_session_id == ctx_session.c.provider_session_id,
                    ),
                )
            )
            .group_by(ctx_session.c.id)
            .order_by(ctx_session.c.time_updated.desc(), ctx_session.c.id.desc())
            .limit(limit)
        )
        return [CtxSession.model_validate(row) for row in self._session.execute(statement).mappings()]

    def session_events(self, *, source_id: int, session_id: str) -> list[CtxSearchCandidate]:
        return _candidate_query(
            self._session,
            "e.source_id = :source_id AND e.provider_session_id = :session_id",
            {"source_id": source_id, "session_id": session_id},
            limit=None,
            ascending=True,
        )

    def event_window(self, selected: CtxSearchCandidate, *, window: int) -> list[CtxSearchCandidate]:
        events = self.session_events(source_id=selected.source_id, session_id=selected.session_id)
        index = next((i for i, event in enumerate(events) if event.event_id == selected.event_id), 0)
        start = max(0, index - window)
        end = min(len(events), index + window + 1)
        return events[start:end]


def _find_session(session: Session, session_id: str) -> CtxSessionSummary | None:
    row = (
        session.execute(
            text(session_summary_sql(predicate_sql="s.provider_session_id = :session_id", include_limit=True)),
            {"session_id": session_id, "limit": 1},
        )
        .mappings()
        .first()
    )
    return CtxSessionSummary.model_validate(row) if row is not None else None


def _candidate_query(
    session: Session,
    predicate: str,
    params: Mapping[str, Any],
    *,
    limit: int | None,
    ascending: bool = False,
) -> list[CtxSearchCandidate]:
    order_direction: CandidateOrder = "ASC" if ascending else "DESC"
    effective_params = dict(params)
    if limit is not None:
        effective_params["limit"] = limit
    rows = session.execute(
        text(candidate_query_sql(predicate_sql=predicate, order=order_direction, include_limit=limit is not None)),
        effective_params,
    ).mappings()
    return candidate_rows(rows)
