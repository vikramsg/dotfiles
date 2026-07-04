---
name: ocint-ctx-history-search
description: Use ocint ctx to search OpenCode local history only before acting when prior OpenCode sessions may contain relevant decisions, attempts, or transcript context.
---

# ocint ctx OpenCode History Search

Use `ocint ctx` when you need to reference previous OpenCode sessions. Those
transcripts can contain user intent, decisions, previous work timelines, past
attempts, and what worked or failed.

Use this skill in two modes:

- retrieval before work, when prior OpenCode sessions may contain decisions,
  commands, failures, or source citations that affect the current task;
- history research reports, when the user asks for a read-only report about a
  historical topic across prior local OpenCode sessions.

## Workflow

1. Confirm OpenCode history is visible when starting from a cold context:

   ```bash
   ocint ctx status
   ocint ctx sources
   ```

   Use `ocint ctx status --json` or `ocint ctx sources --json` only when a
   script needs exact fields.

2. Search with normal language first. Add terms or filters when useful:

   ```bash
   ocint ctx search "<query>"
   ocint ctx search "<query>" --refresh off
   ocint ctx search "<query>" --workspace <workspace>
   ocint ctx search "<query>" --file <path>
   ocint ctx search "<query>" --since 30d
   ocint ctx search "<query>" --term "<related term>" --term "<error text>"
   ocint ctx search "<query>" --session <opencode-session-id>
   ocint ctx search "<query>" --verbose
   ```

   Use default text output for agent reading. Do not add `--json` for search,
   show, or locate unless you are piping it into `jq` or a script, or you need
   exact machine-readable fields. JSON output is much larger and can quickly
   consume the context window.

   When the prompt asks for a topic history or report across multiple sessions,
   run several `ocint ctx search` queries with different wording and filters to
   find promising sessions. Use scoped
   `ocint ctx search "<query>" --session <opencode-session-id>` when a session
   looks relevant and you need dense event-level matches from that session.

   Default search returns primary OpenCode sessions so human intent and
   decisions stay prominent. Use `--include-subagents` when implementation
   details, code review notes, test output, or failure traces from subagent
   sessions are likely to matter.

   Use `--verbose` when you need full OpenCode IDs, citations, and copyable
   follow-up commands without switching to JSON.

   You can write a session transcript to a temporary file, check the file size,
   and then read the relevant parts:

   ```bash
   ocint ctx show session <opencode-session-id> --format markdown --out /tmp/ocint-session.md
   wc -c /tmp/ocint-session.md
   ```

   `--include-current-session` is accepted as a compatibility no-op. This tool
   is OpenCode-only and does not maintain a persistent index or active-session
   exclusion list.

3. Inspect relevant results before relying on them:

   ```bash
   ocint ctx show event <opencode-event-id> --window 5
   ocint ctx show session <opencode-session-id>
   ```

4. Locate original OpenCode material when source identity or resume hints matter:

   ```bash
   ocint ctx locate event <opencode-event-id>
   ocint ctx locate session <opencode-session-id>
   ```

5. Write a transcript of relevant sessions when you, the human, or another agent
   needs a file:

   ```bash
   ocint ctx show session <opencode-session-id> --format markdown --out <output-path>
   ```

## When Search Is Not Enough

Use `ocint ctx sql` only when normal search cannot express the question, such as
counts, joins, audits, or scripts over stable local views. Do not use SQL for
broad transcript text search; `ocint ctx search` is built for that.

Start with the bundled SQL docs:

```bash
ocint ctx docs show sql
ocint ctx docs search "stable views"
```

Common SQL examples:

```bash
ocint ctx sql "SELECT provider, COUNT(*) AS sessions FROM ctx_sessions GROUP BY provider"
ocint ctx sql "SELECT event_type, COUNT(*) AS events FROM ctx_events GROUP BY event_type ORDER BY events DESC"
ocint ctx sql "SELECT path, provider, provider_session_id FROM ctx_files_touched WHERE path LIKE '%AGENTS.md%' LIMIT 20"
```

`ocint ctx sql` is read-only. It installs temporary connection-local views and
does not refresh, import, initialize, migrate, or mutate OpenCode storage.

## History Research Reports

When asked to research a historical topic, stay read-only unless the user also
asks for edits. The agent writes the report; `ocint ctx` only retrieves local
OpenCode source material.

1. Restate the topic, scope, and desired length if the prompt is ambiguous.
   Prefer concise reports by default; use a longer report when the user asks for
   chronology, alternatives, or detailed evidence.
2. Run several targeted searches. Vary query terms across user wording, file or
   module names, error text, commands, branch names, and decision terms. Start
   with `ocint ctx search "<topic>"`, then broaden with `--term` or narrow with
   `--workspace`, `--file`, `--since`, or `--session <opencode-session-id>`.
   Use `--include-subagents` when reviews, implementation attempts, test output,
   or failure traces are likely to live in delegated sessions. Add
   `--refresh off` when the report must not update local state.
3. Inspect focused sources before drawing conclusions. Prefer
   `ocint ctx show event` for a hit plus nearby turns, and
   `ocint ctx show session` when the whole session arc matters:

   ```bash
   ocint ctx show event <opencode-event-id> --window 5
   ocint ctx show session <opencode-session-id>
   ```

   Use full or log mode only when default output omits necessary evidence.
4. Compare evidence across sessions. Note agreements, conflicts, stale results,
   missing raw sources, and gaps where searches did not find evidence.
5. Produce the report as agent synthesis with citations.

Concise report shape:

- answer or finding;
- strongest supporting OpenCode IDs;
- important caveats or gaps;
- optional next search or verification step.

Long report shape:

- question and scope;
- search method, including key queries and filters;
- findings or chronology;
- evidence table with provider `opencode`, OpenCode session ID, OpenCode event
  ID when available, and why each source matters;
- conflicts, gaps, and suggested follow-up.

## Citation Rules

- Cite `ocint ctx` material when it affects your answer or implementation.
- Include provider `opencode`, OpenCode session ID, OpenCode event ID when
  available, source table, and source path when present.
- If you synthesize across multiple snippets, label the conclusion as your
  synthesis and cite the supporting snippets.
- If a source citation is stale or unavailable, say `ocint ctx` returned local
  history text but the raw OpenCode source could not be opened.

## Safety Rules

- Prefer text output for agent reading. Use JSON only for scripts, `jq`, or
  exact field extraction, and keep JSON outputs small.
- Do not say `ocint ctx` inferred a decision unless the cited text explicitly
  states that decision.
- Do not state that `ocint ctx` wrote model analysis.
- Do not paste raw transcripts, large JSON payloads, secrets, tokens, or private
  paths into a user-facing report. Summarize reviewed evidence and quote only
  short excerpts needed to support a claim.
- Treat OpenCode SQLite paths and JSON output as private local history unless
  the user explicitly asks to share reviewed excerpts.

## Loading Note

Restart OpenCode before expecting this external skill to be discovered by future
OpenCode sessions.
