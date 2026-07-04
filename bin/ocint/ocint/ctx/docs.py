from ocint.ctx.models import CtxSearchResult


SQL_DOC = """# ocint ctx SQL

`ocint ctx sql` runs one read-only SELECT or WITH query against temporary stable views installed on the current read-only OpenCode SQLite connection.

Stable views:

- `ctx_sessions`: one row per OpenCode session with `provider`, `provider_session_id`, `session_id`, `parent_id`, `title`, `workspace`, `time_created`, and `time_updated`.
- `ctx_events`: OpenCode `event`, `part`, and `message` rows normalized into `provider`, `provider_session_id`, `event_id`, `source_table`, `event_type`, `time_created`, and `text`.
- `ctx_files_touched`: file-like paths found in OpenCode JSON payloads with source event metadata.
- `ctx_sources`: the OpenCode SQLite source summary.

Examples:

```bash
ocint ctx sql "SELECT provider, COUNT(*) AS sessions FROM ctx_sessions GROUP BY provider"
ocint ctx sql "SELECT event_type, COUNT(*) AS events FROM ctx_events GROUP BY event_type ORDER BY events DESC"
ocint ctx sql "SELECT path, provider, provider_session_id FROM ctx_files_touched LIMIT 20"
ocint ctx sql "SELECT provider, source_type, name, sessions, events FROM ctx_sources"
```

The views are temporary and connection-local. They do not import, refresh, migrate, or mutate OpenCode data.
"""

DOCS = {"sql": SQL_DOC}


def show_doc(topic: str) -> str:
    try:
        return DOCS[topic]
    except KeyError as error:
        raise ValueError(f"Unknown docs topic: {topic}") from error


def search_docs(query: str) -> list[str]:
    terms = [term.lower() for term in query.split() if term]
    matches = []
    for topic, text in DOCS.items():
        lowered = text.lower()
        if all(term in lowered for term in terms):
            matches.append(f"## {topic}\n\n{_snippet(text)}")
    return matches


def _snippet(text: str, *, limit: int = 600) -> str:
    collapsed = "\n".join(line.rstrip() for line in text.strip().splitlines())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"
