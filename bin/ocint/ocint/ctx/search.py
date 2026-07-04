import re

from ocint._timeutil import parse_since_ms
from ocint.ctx.models import CtxSearchRequest, CtxSearchResult
from ocint.ctx.transcript import snippet_text
from ocint.opencode.models import (
    OpenCodeSessionRow,
    OpenCodeUnifiedEventRow,
    payload_paths,
    payload_to_text,
)
from ocint.opencode.repository import OpenCodeRepository


class CtxSearch:
    def __init__(self, repository: OpenCodeRepository) -> None:
        self._repository = repository

    def search(self, request: CtxSearchRequest) -> list[CtxSearchResult]:
        if request.limit is not None and request.limit <= 0:
            raise ValueError("--limit must be greater than zero")
        tokens = _tokens(request.query)
        required_terms = [term.lower() for term in request.terms]
        since_ms = parse_since_ms(request.since)
        sessions = {session.id: session for session in self._repository.sessions()}
        eligible_session_ids = {
            session.id
            for session in sessions.values()
            if (request.include_subagents or session.parent_id is None)
            and (not request.session_id or session.id == request.session_id)
            and (not request.workspace or request.workspace.lower() in _workspace_text(session).lower())
        }
        if not eligible_session_ids:
            return []
        results: list[CtxSearchResult] = []
        for event in self._repository.iter_unified_events_desc(session_ids=eligible_session_ids):
            session = sessions.get(event.session_id or "")
            if session is None:
                continue
            if since_ms is not None and (event.time_created is None or event.time_created < since_ms):
                continue
            candidate = _candidate_text(event, session)
            candidate_lower = candidate.lower()
            if request.file and not _matches_file_filter(event, candidate, request.file):
                continue
            if not all(token in candidate_lower for token in tokens):
                continue
            if not all(term in candidate_lower for term in required_terms):
                continue
            results.append(build_search_result(event, session, candidate))
            if request.limit is not None and len(results) >= request.limit:
                break
        return results


def _tokens(query: str) -> list[str]:
    return re.findall(r"[\w./-]+", query.lower())


def _candidate_text(event: OpenCodeUnifiedEventRow, session: OpenCodeSessionRow) -> str:
    items = [
        session.id,
        session.title,
        session.cwd,
        session.data.directory,
        session.data.workspace,
        event.id,
        event.event_type,
        event.source_path,
        payload_to_text(event.data),
    ]
    return " ".join(
        item
        for item in items
        if item
    )


def _workspace_text(session: OpenCodeSessionRow) -> str:
    return " ".join(item for item in [session.cwd, session.data.directory, session.data.workspace, session.data.cwd, session.data.path, session.title] if item)


def _matches_file_filter(event: OpenCodeUnifiedEventRow, candidate: str, file_filter: str) -> bool:
    filter_lower = file_filter.lower()
    paths = payload_paths(event.data)
    if event.source_path and event.source_path not in paths:
        paths.insert(0, event.source_path)
    if paths:
        return any(filter_lower in path.lower() for path in paths)
    return filter_lower in candidate.lower()


def build_search_result(event: OpenCodeUnifiedEventRow, session: OpenCodeSessionRow, candidate: str) -> CtxSearchResult:
    snippet = snippet_text(candidate)
    citation = f"opencode session={session.id} event={event.id} table={event.source_table}"
    return CtxSearchResult(
        session_id=session.id,
        event_id=event.id,
        source_table=event.source_table,
        event_type=event.event_type,
        time_created=event.time_created,
        title=session.title,
        workspace=session.cwd or session.data.directory or session.data.workspace or session.data.cwd or session.data.path,
        source_path=event.source_path,
        snippet=snippet,
        citation=citation,
        follow_up=f"ocint ctx show event {event.id} --window 5",
    )
