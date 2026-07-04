from ocint.opencode.models import OpenCodeUnifiedEventRow, payload_to_text


def event_text(event: OpenCodeUnifiedEventRow) -> str:
    return payload_to_text(event.data)


def snippet_text(text: str, *, limit: int = 220) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"
