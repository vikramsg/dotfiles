SQL_DOC = """# ocint ctx SQL

`ocint ctx sql` runs one read-only SELECT or WITH query against stable views in the imported ocint ctx index. Run `ocint ctx import` first to populate the index from OpenCode. SQLite is the default ctx backend; pass `ocint ctx --backend duckdb ...` or set `OCINT_CTX_BACKEND=duckdb` to use DuckDB.

Stable views:

- `ctx_sessions`: one row per imported OpenCode session with `provider`, `provider_session_id`, `session_id`, `parent_id`, `title`, `workspace`, `time_created`, and `time_updated`.
- `ctx_events`: imported OpenCode `event`, `part`, and `message` rows normalized into `provider`, `provider_session_id`, `event_id`, `source_table`, `event_type`, `time_created`, `text`, `source_path`, and `citation`.
- `ctx_files_touched`: file-like paths found in OpenCode JSON payloads with source event metadata.
- `ctx_sources`: imported OpenCode SQLite source metadata and counts.

Examples:

```bash
ocint ctx sql "SELECT provider, COUNT(*) AS sessions FROM ctx_sessions GROUP BY provider"
ocint ctx sql "SELECT event_type, COUNT(*) AS events FROM ctx_events GROUP BY event_type ORDER BY events DESC"
ocint ctx sql "SELECT path, provider, provider_session_id FROM ctx_files_touched LIMIT 20"
ocint ctx sql "SELECT provider, source_type, name, sessions, events FROM ctx_sources"
```

These stable views are backend-neutral projections. User SQL is executed only inside an in-memory SQLite sandbox populated from those projections, never directly against DuckDB or internal ctx tables. They never read or mutate OpenCode directly; only `ocint ctx import` reads the OpenCode source in read-only mode.
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
