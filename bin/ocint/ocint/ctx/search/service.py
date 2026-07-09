import json
import re
from collections.abc import Mapping
from typing import Any

from ocint._timeutil import parse_since_ms
from ocint.ctx.models import CtxSearchCandidate, CtxSearchRequest, CtxSearchResult
from ocint.ctx.search.repository import CtxSearchRepository
from ocint.ctx.transcript import snippet_text


def search_history(request: CtxSearchRequest, repository: CtxSearchRepository) -> list[CtxSearchResult]:
    if request.limit is not None and request.limit <= 0:
        raise ValueError("--limit must be greater than zero")
    tokens = _tokens(request.query)
    required_terms = [term.lower() for term in request.terms]
    exclude_session_tree_root_id = None if request.include_current_session else request.active_session_id
    candidates = repository.search_events(
        query_tokens=tokens,
        required_terms=required_terms,
        since_ms=parse_since_ms(request.since),
        session_id=request.session_id,
        workspace=request.workspace,
        file_filter=request.file,
        include_subagents=request.include_subagents,
        exclude_session_tree_root_id=exclude_session_tree_root_id,
        limit=request.limit,
    )
    return [build_search_result(candidate) for candidate in candidates]


def build_search_result(candidate: CtxSearchCandidate) -> CtxSearchResult:
    snippet_source = _semantic_snippet_source(candidate)
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
        snippet=_display_snippet(snippet_source),
        citation=candidate.citation,
        follow_up=f"ocint ctx show event {candidate.event_id} --window 5",
    )


def _tokens(query: str) -> list[str]:
    return re.findall(r"[\w./-]+", query.lower())


def _display_snippet(text: str) -> str:
    if "\n" not in text:
        return snippet_text(text)
    collapsed_lines = [" ".join(line.split()) for line in text.splitlines()]
    collapsed = "\n".join(line for line in collapsed_lines if line)
    if len(collapsed) <= 220:
        return collapsed
    return collapsed[:219].rstrip() + "…"


def _semantic_snippet_source(candidate: CtxSearchCandidate) -> str:
    payload = _payload(candidate.payload_json)
    event_type = candidate.event_type.lower()
    if payload is not None:
        if event_type == "tool" and (tool_text := _tool_text(payload)):
            return tool_text
        if event_type in {"assistant", "user", "system", "text", "part"} and (
            text := _first_text(payload, ["text", "content", "message"])
        ):
            return text
        if event_type == "file.patch" and (text := _first_text(payload, ["text", "content", "summary", "message"])):
            return text
        if text := _first_text(payload, ["text", "content", "message", "output", "result", "summary"]):
            return text
    return _clean_fallback_text(candidate.full_text or candidate.search_text, event_type=event_type)


def _payload(payload_json: str) -> Mapping[str, Any] | None:
    try:
        value = json.loads(payload_json)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, Mapping) else None


def _tool_text(payload: Mapping[str, Any]) -> str:
    header_parts = [
        _first_text(payload, ["tool", "name", "toolName", "tool_name", "command", "action"]),
        _first_text(payload, ["callID", "callId", "call_id", "call", "callID", "id"]),
        _first_text(payload, ["status", "state"]),
    ]
    lines = [" ".join(part for part in header_parts if part)]
    if path := _first_text(payload, ["path", "file", "filePath", "filepath", "sourcePath"]):
        lines.append(path)
    if output := _first_text(
        payload, ["text", "content", "output", "result", "message", "summary", "stdout", "stderr"]
    ):
        lines.append(output)
    return "\n".join(line for line in lines if line)


def _first_text(value: Any, keys: list[str]) -> str | None:
    for key in keys:
        if text := _find_text(value, key):
            return text
    return None


def _find_text(value: Any, target_key: str) -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) == target_key and isinstance(item, str) and item.strip():
                return item.strip()
        for item in value.values():
            if text := _find_text(item, target_key):
                return text
    if isinstance(value, list):
        for item in value:
            if text := _find_text(item, target_key):
                return text
    return None


def _clean_fallback_text(text: str, *, event_type: str) -> str:
    cleaned = text.strip()
    if event_type and cleaned.lower().startswith(f"{event_type} "):
        cleaned = cleaned[len(event_type) :].strip()
    parts = cleaned.split()
    while parts and _numeric_token(parts[0]):
        parts.pop(0)
    return " ".join(parts) if parts else cleaned


def _numeric_token(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True
