import re

from ocint._timeutil import parse_since_ms
from ocint.ctx.models import CtxSearchCandidate, CtxSearchRequest, CtxSearchResult
from ocint.ctx.repository import CtxSearchRepository
from ocint.ctx.transcript import snippet_text


def search_history(request: CtxSearchRequest, repository: CtxSearchRepository) -> list[CtxSearchResult]:
    if request.limit is not None and request.limit <= 0:
        raise ValueError("--limit must be greater than zero")
    tokens = _tokens(request.query)
    required_terms = [term.lower() for term in request.terms]
    candidates = repository.search_events(
        query=request.query,
        query_tokens=tokens,
        required_terms=required_terms,
        since_ms=parse_since_ms(request.since),
        session_id=request.session_id,
        workspace=request.workspace,
        file_filter=request.file,
        include_subagents=request.include_subagents,
        limit=request.limit,
    )
    return [build_search_result(candidate) for candidate in candidates]


def build_search_result(candidate: CtxSearchCandidate) -> CtxSearchResult:
    return CtxSearchResult(
        provider=candidate.provider,
        session_id=candidate.session_id,
        event_id=candidate.event_id,
        source_table=candidate.source_table,
        event_type=candidate.event_type,
        time_created=candidate.time_created,
        title=candidate.title,
        workspace=candidate.workspace,
        source_path=candidate.source_path,
        snippet=snippet_text(candidate.search_text),
        citation=candidate.citation,
        follow_up=f"ocint ctx show event {candidate.event_id} --window 5",
    )


def _tokens(query: str) -> list[str]:
    return re.findall(r"[\w./-]+", query.lower())
