# ctx Internals Notes For ocint ctx

## Purpose

This document records how upstream `ctx` makes local agent-history search and
structured queries fast, so `ocint ctx` can copy the useful parts without
copying unrelated product surface. The scope is upstream `ctx` only; `ocint ctx`
is mentioned only as the consumer of these notes. [W1] [W2]

## Upstream ctx Mental Model

`ctx` is index-first. It imports provider-owned local agent histories into a
normalized local SQLite store, then searches that store instead of reparsing raw
transcripts for every query. Official docs describe this as turning local
coding-agent history into a searchable SQLite index. [W1]

The practical optimization model is:

- do provider parsing once during setup/import/refresh;
- normalize provider-specific records into sessions, events, files, sources, and citations;
- write search-specific SQLite projections;
- query those projections with bounded result sizes;
- render cited snippets and follow-up commands from indexed metadata. [W1] [W2] [S1] [S2]

For `ocint ctx`, the direct lesson is that fast search should avoid repeatedly
hydrating and scanning all OpenCode rows for every query once the corpus gets
large.

## End-To-End Data Flow

### Discovery

`ctx sources` discovers supported local provider history locations and configured
custom history-source plugins without launching those providers. Discovery tells
the user whether a source is visible and importable on the current machine. [W1]

### Import

`ctx setup` and `ctx import` read provider-owned local history and write ctx-owned
SQLite rows. Import is local: it does not call model APIs, require API keys, or
write into source repositories. [W1] [W4]

### Normalization

Provider histories can be JSONL trees, provider SQLite databases, or session
state files. `ctx` preserves useful provider metadata, then normalizes the data
into ctx-owned sessions, events, citations, and searchable text. [W1] [S1]

### Search Execution

`ctx search` can first do a quiet best-effort refresh, then queries the local
SQLite store and returns ranked cited results. Default output is shaped around
useful sessions, while `--events` and `--session` request denser event-level
matches. [W2] [W4] [S2] [S3]

### Retrieval

`ctx show event`, `ctx show session`, `ctx locate event`, and `ctx locate session`
use ctx-owned IDs returned by search to retrieve surrounding context or source
provenance. This separates discovery from verification. [W1] [W2]

## Storage Layout

### Data Root

The default ctx data root is `~/.ctx`, with `work.sqlite` as the primary local
store. `CTX_DATA_ROOT` or `--data-root` can point ctx elsewhere. [W3]

### SQLite Contents

The SQLite store can contain provider metadata, source paths, session IDs, event
IDs, timestamps, working directories, normalized text, bounded output previews,
searchable text, citations, and import cursors. If text is searchable, assume a
copy or normalized form exists in SQLite. [W3]

`ctx` also creates many regular B-tree indexes over metadata tables, including
sessions, events, runs, source import state, and touched-file paths. These indexes
support lookup, filtering, and joins outside the full-text path. [S1]

## Normalized Entities

### Sessions

Sessions are durable conversation units. They support default search clustering,
`ctx show session`, and `ctx locate session`. Session rows preserve provider,
provider session ID, parent/root session IDs, agent type, primary-session flags,
timestamps, and source metadata. [W1] [S1]

### OpenCode Forks

OpenCode has a session fork API and a `session.parent_id` column, but the
inspected fork implementation creates a new session by copying messages from the
source session and does not pass `parentID` to the new session. The copied
message IDs and message-level parent links are rewritten inside the new session,
so manual forks appear as independent root sessions in the OpenCode session
table. See OpenCode `ForkInput`, `Session.fork`, `Session.children`, and
`SessionTable.parent_id` in
[`session.ts`](https://github.com/anomalyco/opencode/blob/f52424e05fab0edddb4462112ceb02044085f903/packages/opencode/src/session/session.ts#L273-L276),
[`session.ts`](https://github.com/anomalyco/opencode/blob/f52424e05fab0edddb4462112ceb02044085f903/packages/opencode/src/session/session.ts#L693-L733),
[`session.ts`](https://github.com/anomalyco/opencode/blob/f52424e05fab0edddb4462112ceb02044085f903/packages/opencode/src/session/session.ts#L598-L605),
and [`sql.ts`](https://github.com/anomalyco/opencode/blob/f52424e05fab0edddb4462112ceb02044085f903/packages/core/src/session/sql.ts#L22-L65).

Upstream `ctx` models OpenCode `session.parent_id` as parent-child lineage. When
`parent_id` is present, the imported session gets parent/root metadata and is
treated as a child/subagent-style session. When `parent_id` is absent, the
session imports as a primary/root session. Therefore, OpenCode manual forks are
not distinguishable as forks by upstream `ctx` unless OpenCode stores fork
lineage in a field the importer reads. The relevant ctx OpenCode importer logic
is in [`ctx-history-capture`](https://github.com/ctxrs/ctx/blob/eb4df7da5825245c9ca53a02382585445f64c4b4/crates/ctx-history-capture/src/lib.rs#L9348-L9417)
and the OpenCode session row reader is in
[`ctx-history-capture`](https://github.com/ctxrs/ctx/blob/eb4df7da5825245c9ca53a02382585445f64c4b4/crates/ctx-history-capture/src/lib.rs#L9452-L9505).


### Events

Events are searchable timeline items such as messages, tool calls, tool output,
command events, file touched events, summaries, and notices. Event rows are what
the fast event-search path returns when dense matching is needed. [W1] [S1] [S2]

### Runs

Runs store command/tool execution metadata and connect command previews, status,
working directories, inputs, and outputs back to sessions and history records.
They give search results more context than raw transcript text alone. [S1]

### Files Touched

`files_touched` rows are indexed path metadata. They let `--file` find sessions,
events, runs, records, and sources related to a path without scanning current
files or raw transcript JSON. [W2] [S1]

### Capture Sources

Capture sources preserve provider/source provenance: provider name, source path,
external session ID, working directory, cursor metadata, and source-specific
metadata. Search results and citations use this to let agents verify where a hit
came from. [W1] [S1]

### Citations

Search results carry citations with ctx IDs, provider metadata, event sequence,
source path, cursor, and source availability when known. The product contract is
retrieval with enough provenance for verification, not model interpretation. [W1]
[W2]

## Search Projections

Search projections are the main speed mechanism. `ctx` stores searchable text in
SQLite FTS5 virtual tables so search can use SQLite full-text lookup rather than
application-level substring scans over raw payloads. [S1]

### Record Search Projection

`ctx_history_search` stores record-level searchable fields such as title, summary,
primary user text, context text, and tags. Record searches can use this table to
quickly find promising history records. [S1]

### Event Search Projection

`event_search` stores event IDs, related record/session IDs, roles, preview text,
and rank buckets. This projection powers the fast event-search path and dense
event-level matching. [S1] [S2]

### Artifact Search Projection

`artifact_search` stores searchable artifact preview text where available. Record
search can union artifact matches with record and event matches before grouping
back to history records. [S1]

## FTS Query Construction

### Tokenization

The store turns user text into FTS terms by splitting on whitespace, trimming
non-word punctuation around each term, keeping alphanumeric terms, quoting them,
and joining them with `AND`. Empty or invalid term sets return no FTS query. [S1]

### FTS Match Query

Record search uses `ctx_history_search MATCH ?`, `event_search MATCH ?`, and
`artifact_search MATCH ?` with `bm25(...)` scoring. Event search uses
`event_search MATCH ?` and returns event metadata plus preview text. [S1]

### Fallback Behavior

If FTS tables are unavailable, record search can fall back to a simple `LIKE`
query over title/body/tags. The optimized path is still FTS; broad transcript
text search should use `ctx search`, not SQL over payload JSON. [S1] [S4]

## Ranking

### BM25 Ranking

SQLite FTS `bm25(...)` provides the first ordering signal for record and event
matches. Lower BM25 scores are better, so the search layer converts event scores
into positive normalized ranks for output. [S1] [S2]

### Tie-Breaks

Event hits are ordered by BM25, then event time descending, sequence descending,
and event ID. Record results use BM25 and stable IDs. Candidate sorting also uses
score, updated time, title, and ID for deterministic output. [S1] [S2]

### Rank Normalization

Search results normalize ranks relative to the maximum rank in the current result
set and clamp them to `0.0..=1.0`. Session results also get a session-importance
score with a coverage boost for additional matches in that session. [S2]

## Fast Event Search Path

### Activation Conditions

`fast_event_search_packet` activates for non-empty queries when the store has at
least a large-event-corpus threshold and the query does not use history-source
filters. In the inspected source, the threshold is `1_024` events. [S2]

### Page Size And Budgets

The fast path requests event FTS pages from the store. Page size grows when
results are clustered or filtered, and the loop has a maximum page budget so a
selective filter cannot scan indefinitely. [S2]

### Early Stopping

The fast path stops when it has enough results, the FTS page is smaller than the
requested page size, or the scan budget is exhausted. This is the key runtime
guard for large histories. [S2]

## Session-Diverse Results

### Session Clustering

Default search returns session-diverse results. In session result mode, ctx keeps
one top result per session or record and skips later hits from the same cluster.
[W2] [S2]

### More Matches In Session

When later hits belong to a session already represented in the output, ctx
increments `more_matches_in_session` and updates `session_importance` instead of
printing every hit. This reduces duplicate output and token use. [W2] [S2]

### Dense Event Mode

`--events` returns dense event-level results across sessions. `--session
<ctx-session-id>` is the follow-up mode after default search finds a promising
session and the user wants all relevant event hits inside it. [W2] [W4]

## Filter Model

### Provider And Source Filters

Search filters can narrow by provider, custom history source, provider key,
source ID, and source format. The CLI builds these filters before calling the
search crate. [W2] [S3]

### Workspace And Time Filters

Workspace filtering matches stored workspace/cwd/source-path/repository text.
`--since` filters events by time. These filters are applied to indexed candidate
metadata instead of requiring raw transcript scans. [W2] [S2] [S3]

### Session And Agent Scope Filters

Default search emphasizes primary-agent sessions. `--include-subagents` expands
the scope to implementation details, review notes, and failure traces from
subagents. In Codex, ctx excludes the active session tree by default when
`CODEX_THREAD_ID` is available unless `--include-current-session` is set. [W2]
[S2] [S3]

### Event Type Filters

`--event-type` can restrict results to messages, tool calls, tool output, command
events, file touched events, summaries, notices, and related normalized event
types. [W2] [S2]

## File Search Model

### Path Matching

`--file` uses indexed touched-file path metadata. The store matches exact paths,
old paths, and suffix-style path matches. [W2] [S1]

### Scope Expansion

File matches expand into a `FileTouchScope` containing related history record
IDs, session IDs, run IDs, event IDs, and source IDs. Search then filters
candidate hits against that scope. [S1] [S2]

### Not A Filesystem Scan

`--file` searches paths recorded during import. It does not inspect the current
filesystem, so it is stable even when the repository has changed since the old
session. [W2]

## Refresh Behavior

`ctx` refresh is search-time index catch-up, not live transcript querying. 
The CLI refresh flag exists on `ctx search` only: `--refresh auto|off|strict`.
`auto` attempts a best-effort pre-search import of discovered refreshable
sources, then searches the local index; `off` skips imports and searches the
existing index only; `strict` fails if refresh cannot complete. `ctx setup` and
`ctx import` update the index directly but do not use a refresh flag. `ctx show`,
`ctx locate`, `ctx sql`, and MCP search/query paths read the existing index only.
[W2] [W4] [S3]


### Refresh Auto

`--refresh auto` is the default. It attempts a best-effort pre-search import of
discovered native provider sources and enabled custom history plugins, then can
serve the existing index if refresh fails and an index already exists. [W2] [W4]
[S3]

For SQLite-backed providers such as OpenCode, refresh runs in the foreground
during the `ctx search` process and can still reread provider rows before
deduped writes skip existing indexed events, so `--refresh off` is the
predictable low-latency path when freshness is not required.

### Refresh Off

`--refresh off` skips provider imports and plugin execution and searches the
existing index only. The CLI opens an existing store read-only for this path. [W2]
[W4] [S3] [G3]

### Refresh Strict

`--refresh strict` fails the search if the pre-search refresh cannot run or
import successfully. It is useful when freshness matters more than latency or
availability. [W2] [W4] [S3]

## Incremental Index Maintenance

### Event Projection Updates

Event upserts update the event FTS projection for the changed event. Event
insert-if-absent inserts the FTS projection only when the event row is new. This
avoids rebuilding event search for every normal event write. [S1]

### Search Projection Rebuilds

Full projection rebuilds still exist for migration, import archive, and explicit
search-index refresh paths. Rebuilds delete projection rows and repopulate FTS
tables from normalized rows. [S1]

### Import Checkpoints

Append-only provider histories need checkpoints so refresh can import only new
tail bytes instead of reprocessing old events. A ctx issue and merged fix split
current-file indexed metadata from explicit import checkpoints and validate
checkpoint prefix hashes for safe tail import. [G1] [G2]

## Read-Only SQL Path

### Stable Views

`ctx sql` is for structured inspection that normal search does not express:
counts, joins, audits, and scripts. Stable views include `ctx_sessions`,
`ctx_events`, `ctx_files_touched`, and `ctx_sources`. [S1] [S4]

### Read-Only Store Opening

The CLI opens an existing store read-only for `ctx sql`. The store uses SQLite
read-only open flags and enables `PRAGMA query_only = ON`. [S1] [S3]

### SQL Limits

`raw_sql_query` rejects empty SQL, multiple statements, parameters, non-read-only
statements, and excessive columns. It enforces row, column, SQL-byte, value-byte,
and result-preview budgets, and installs a progress handler for timeouts. [S1]

## Show And Locate

### Show Event

`ctx show event <ctx-event-id>` opens a selected event with neighboring session
context. This is the normal verification path after search finds a promising
event. [W1] [W2]

### Show Session

`ctx show session <ctx-session-id>` opens the whole session. It can render compact,
full, log, JSON, or markdown output depending on command options. [W1] [W4]

### Locate

`ctx locate event` and `ctx locate session` report source metadata such as
provider source path and cursor when known. This gives agents enough provenance
to verify important retrieved context. [W1] [W2]

## References

### Official Docs

- [W1] `https://ctx.rs/concepts/how-it-works/` - official description of discovery, import, normalized sessions/events, SQLite storage, search/retrieval, and refresh behavior.
- [W2] `https://ctx.rs/search/` - official search workflow: session-diverse results, filters, refresh modes, machine output, and cited retrieval.
- [W3] `https://ctx.rs/reference/storage/` - official storage/privacy page describing `~/.ctx`, `work.sqlite`, and what searchable SQLite data contains.
- [W4] `https://ctx.rs/reference/cli/` - official CLI reference for setup/import/search/show/locate/SQL behavior, defaults, and limits.

### Source Files

- [S1] `https://github.com/ctxrs/ctx/blob/eb4df7da5825245c9ca53a02382585445f64c4b4/crates/ctx-history-store/src/lib.rs` - SQLite schema, B-tree indexes, FTS5 projections, FTS queries, file-touch scope, read-only SQL, store opening, and projection maintenance.
- [S2] `https://github.com/ctxrs/ctx/blob/eb4df7da5825245c9ca53a02382585445f64c4b4/crates/ctx-history-search/src/lib.rs` - search packet construction, fast event search, filtering, ranking, snippets, clustering, and pagination/truncation.
- [S3] `https://github.com/ctxrs/ctx/blob/eb4df7da5825245c9ca53a02382585445f64c4b4/crates/ctx-cli/src/main.rs` - CLI search flow, refresh behavior, filter construction, read-only store opening, and SQL command flow.
- [S4] `https://github.com/ctxrs/ctx/blob/eb4df7da5825245c9ca53a02382585445f64c4b4/skills/ctx-agent-history-search/SKILL.md` - agent-facing workflow and guidance that `ctx sql` is for structured inspection, not broad transcript text search.

### GitHub Issues And PRs

- [G1] `https://github.com/ctxrs/ctx/issues/16` - issue describing checkpoint semantics needed to keep append-only Codex refresh efficient and avoid reprocessing old events.
- [G2] `https://github.com/ctxrs/ctx/pull/17` - merged PR adding explicit checkpoint state and safe appended-byte tail import behavior.
- [G3] `https://github.com/ctxrs/ctx/pull/27` - merged PR hardening read-only `--refresh off`, search fallback, and doctor paths so inspection commands do not initialize or mutate stores unexpectedly.
