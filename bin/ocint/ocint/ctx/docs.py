from ocint.ctx.models import CtxDocTopic


def docs_catalog() -> tuple[CtxDocTopic, ...]:
    return (
        CtxDocTopic(name="quickstart", summary="First useful commands", body=_quickstart_doc()),
        CtxDocTopic(name="commands", summary="Command overview", body=_commands_doc()),
        CtxDocTopic(name="discovery", summary="How to find session IDs", body=_discovery_doc()),
        CtxDocTopic(
            name="refresh", summary="Auto refresh, stale-while-revalidate, and --refresh off", body=_refresh_doc()
        ),
        CtxDocTopic(name="sql", summary="Stable SQL views and examples", body=_sql_doc()),
    )


def show_doc(topic: str) -> str:
    for item in docs_catalog():
        if item.name == topic:
            return item.body
    topics = ", ".join(item.name for item in docs_catalog())
    raise ValueError(f"Unknown docs topic: {topic}. Available topics: {topics}")


def render_doc_topics() -> str:
    rows = "\n".join(f"{item.name:<10} {item.summary}" for item in docs_catalog())
    return f"Available topics\n\n{rows}\n\nShow a topic:\n  ocint ctx docs show quickstart\n"


def search_docs(query: str) -> list[str]:
    terms = [term.lower() for term in query.split() if term]
    matches = []
    for topic in docs_catalog():
        text = f"{topic.name}\n{topic.summary}\n{topic.body}"
        lowered = text.lower()
        if all(term in lowered for term in terms):
            matches.append(f"## {topic.name}\n\n{_snippet(topic.body)}")
    return matches


def _quickstart_doc() -> str:
    return """# ocint ctx quickstart

Start with search when you remember words from a prior OpenCode session:

```bash
ocint ctx search "what you remember"
```

Default search creates or refreshes a missing ctx index before searching. Once the index is ready, repeated searches use the index immediately and refresh stale data in the background. After that, read commands use the imported ocint ctx index:

```bash
ocint ctx show session
ocint ctx show session <session-id>
ocint ctx show event <event-id> --window 5
ocint ctx sources
```

Use `ocint ctx show session` with no session ID to discover recent session IDs.
"""


def _commands_doc() -> str:
    return """# ocint ctx commands

- `ocint ctx search "<query>"`: search prior OpenCode history; auto refreshes missing indexes and refreshes stale ready indexes in the background.
- `ocint ctx show session`: list recent sessions when no ID is supplied.
- `ocint ctx show session <session-id>`: render a session transcript.
- `ocint ctx show event <event-id>`: render one event with nearby context.
- `ocint ctx locate session <session-id>` and `ocint ctx locate event <event-id>`: show source identity and provenance.
- `ocint ctx docs show`: list docs topics.
- `ocint ctx sql "<select>"`: query stable imported ctx views.
- `ocint ctx import`: prebuild or refresh the ctx index explicitly.
"""


def _discovery_doc() -> str:
    return """# ocint ctx discovery

If you do not know a session ID, start here:

```bash
ocint ctx show session
```

That lists recent imported sessions and prints a copyable `ocint ctx show session <session-id>` follow-up. Search results also include session and event IDs:

```bash
ocint ctx search "error text" --verbose
```

Use SQL only when you need counts, ordering, or ad-hoc audits over stable views.
"""


def _refresh_doc() -> str:
    return """# ocint ctx refresh

Default search is the normal first command:

```bash
ocint ctx search "what you remember"
```

Default `auto` search refreshes in the foreground only when there is no ready index to search. If the index is ready but stale, search results render first and a detached worker refreshes the ctx index for later commands.

`--refresh off` never imports, never parses refresh TTL config, and only reads an existing ready index:

```bash
ocint ctx search "what you remember" --refresh off
```

Use `--refresh off` when you intentionally want index-only behavior. If no ready index exists, run default search without `--refresh off`, or run `ocint ctx import`.
"""


def _sql_doc() -> str:
    return """# ocint ctx SQL

`ocint ctx sql` runs one read-only SELECT or WITH query against stable views in the imported ocint ctx index. Run `ocint ctx search "what you remember"` or `ocint ctx import` first to populate the index from OpenCode.

Stable views:

- `ctx_sessions`: one row per imported OpenCode session with `provider`, `provider_session_id`, `session_id`, `parent_id`, `title`, `workspace`, `time_created`, and `time_updated`.
- `ctx_events`: imported OpenCode `message` and `part` transcript rows normalized into `provider`, `provider_session_id`, `event_id`, `source_table`, `event_type`, `time_created`, `text`, `source_path`, and `citation`.
- `ctx_files_touched`: file-like paths found in OpenCode JSON payloads with source event metadata.
- `ctx_sources`: imported OpenCode SQLite source metadata and counts.

Examples:

```bash
ocint ctx sql "SELECT provider, COUNT(*) AS sessions FROM ctx_sessions GROUP BY provider"
ocint ctx sql "SELECT event_type, COUNT(*) AS events FROM ctx_events GROUP BY event_type ORDER BY events DESC"
ocint ctx sql "SELECT path, provider, provider_session_id FROM ctx_files_touched LIMIT 20"
ocint ctx sql "SELECT provider, source_type, name, sessions, events FROM ctx_sources"
```

These stable views are persistent objects in the ocint-owned ctx SQLite database. They never read or mutate OpenCode directly; only `ocint ctx import` and default `ocint ctx search` read the OpenCode source in read-only mode.
"""


def _snippet(text: str, *, limit: int = 600) -> str:
    collapsed = "\n".join(line.rstrip() for line in text.strip().splitlines())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"
