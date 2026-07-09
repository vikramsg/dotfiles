---
name: ocint-ctx-history-search
description: Use ocint ctx to search local OpenCode history before acting. Use when prior OpenCode sessions may contain relevant decisions, attempts, transcript context, or source citations.
---

# ocint ctx OpenCode History Search

Use `ocint ctx` when local OpenCode history may contain useful context for the
current task.

## Workflow

1. Confirm OpenCode history is available:

   ```bash
   ocint ctx status
   ocint ctx status --json
   ocint ctx sources
   ocint ctx sources --json
   ```

   Prefer text output for agent reading. Use JSON only for scripts or exact field
   extraction.

2. Search with normal language first, then add filters as needed:

   ```bash
   ocint ctx search "<query>"
   ocint ctx search "<query>" --refresh off
   ocint ctx search "<query>" --content tools
   ocint ctx search "<query>" --content all
   ocint ctx search "<query>" --workspace <workspace>
   ocint ctx search "<query>" --file <path>
   ocint ctx search "<query>" --since 30d
   ocint ctx search "<query>" --term "<related term>" --term "<error text>"
   ocint ctx search "<query>" --session <session-id>
   ocint ctx search "<query>" --verbose
   ocint ctx search "<query>" --include-subagents
   ```

   Default search focuses on primary sessions and text events (limit 20). Use
   `--content tools` or `--content all` when tool output matters. Add
   `--include-subagents` when implementation details, review notes, failure
   traces, or test output from child sessions are likely to matter. Default
   search may refresh the index in the background (TTL default 60m). Use
   `--refresh off` for index-only search.

3. Inspect promising matches before relying on them:

   ```bash
   ocint ctx show event <event-id> --window 5
   ocint ctx show event <event-id> --window 0 --json
   ocint ctx show session <session-id> --mode lite --out /tmp/ocint-session-lite.txt
   ocint ctx show session <session-id> --mode full --out /tmp/ocint-session-full.txt
   ocint ctx show session <session-id> --format markdown --out /tmp/ocint-session.md
   ```

   Use `--mode full` when the excerpt omits necessary evidence. Session and event
   JSON output is larger than text output; reserve it for exact field extraction.

4. Locate source identity when you need stable IDs or raw database provenance:

   ```bash
   ocint ctx locate event <event-id>
   ocint ctx locate event <event-id> --json
   ocint ctx locate session <session-id>
   ocint ctx locate session <session-id> --json
   ```

## SQL for Counts and Audits

Use SQL only when normal search cannot express the question, such as counts,
joins, or audits over stable local views. Start with the bundled docs:

```bash
ocint ctx docs show sql
ocint ctx docs search "stable views"
```

`ocint ctx sql` accepts one read-only `SELECT` or `WITH` statement over these
stable views only: `ctx_sessions`, `ctx_events`, `ctx_files_touched`, and
`ctx_sources`.

```bash
ocint ctx sql "SELECT provider, COUNT(*) AS sessions FROM ctx_sessions GROUP BY provider"
ocint ctx sql "SELECT event_type, COUNT(*) AS events FROM ctx_events GROUP BY event_type ORDER BY events DESC"
ocint ctx sql "SELECT path, provider, provider_session_id FROM ctx_files_touched LIMIT 20"
ocint ctx sql "SELECT provider, source_type, name, sessions, events FROM ctx_sources"
```

## Reporting Guidance

- Cite `ocint ctx` material when it affects your answer or implementation.
- Include session IDs, event IDs, and source paths when they are relevant.
- Treat local history as private. Summarize evidence and quote only short
  excerpts needed to support a claim.
- Do not claim a decision was made unless the cited history explicitly says so.
