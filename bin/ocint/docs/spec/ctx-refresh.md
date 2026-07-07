# ctx Refresh Spec

`ocint ctx` refresh keeps the ocint-owned ctx index aligned with OpenCode history without making normal search feel slow.

The preferred user experience is stale-while-revalidate: search MUST read the existing ready index immediately, then refresh in the background for the next command when the index is stale.

## Purpose

Refresh exists because `ocint ctx search` depends on an imported ctx index, while OpenCode history changes outside ocint.

The refresh design MUST optimize for fast repeated search. A user who already has a ready ctx index MUST NOT wait for a full import before seeing search results.

Refresh MUST also preserve correctness. The ctx index MUST eventually include new OpenCode rows, update changed rows, and remove rows that disappeared from the OpenCode source.

## Source And Index

The OpenCode SQLite database is the read-only source. ocint MUST never migrate, write, or attach writable state to the OpenCode database.

The ctx SQLite database is owned by ocint. Alembic migrations, ctx tables, FTS tables, stable views, checkpoints, locks, and refresh metadata belong to the ctx side only.

`ctx_source` identifies an imported source and stores source identity/count metadata. Refresh timing, refresh status, checkpoints, watermarks, and diagnostics are refresh state, not source identity.

## Readiness

A ready ctx index is one that exists, has the expected Alembic revision, has the required physical tables, has the expected FTS table shape, and has the stable SQL views expected by the current code.

Search MUST read only a ready ctx index. If no ready ctx index exists, default search MUST run a foreground import before searching because there is no stale index to use.

`--refresh off` MUST NOT create, migrate, or refresh the ctx index. If the index is missing or not ready, it MUST fail with a recovery hint.

## Refresh Modes

Refresh mode is command orchestration. Search itself reads indexed ctx history and MUST NOT own import policy.

### off

`off` never refreshes.

Search opens the existing ready ctx index and reads it. Missing or unready ctx infrastructure is an error.

This mode is for deterministic index-only behavior.

### auto

`auto` is the default search mode.

If the ctx index is missing or not ready, search imports in the foreground, then reads the freshly imported index.

If the ctx index is ready and fresh, search reads it immediately and does not start refresh work.

If the ctx index is ready and stale, search reads it immediately and schedules background refresh for a later command to observe.

## TTL

TTL controls how often `auto` refresh attempts are allowed.

Freshness is based on the most recent successful refresh for the OpenCode source.

TTL checks MUST use the refresh state's latest successful refresh completion time. Failed, skipped, and running refresh attempts MUST NOT update freshness.

The default TTL MUST be long enough to make repeated searches fast and short enough that new history appears soon. The default is `1h`.

TTL MUST be configurable without requiring code changes. The first supported configuration surface is an environment variable such as `OCINT_CTX_REFRESH_TTL`, using simple durations like `30s`, `10m`, `1h`, and `0`.

`0` means always stale in `auto` mode. It MUST NOT mean refresh is disabled; `--refresh off` is the disable switch.

## Refresh Policy

TTL, checkpoints, and watermarks have separate responsibilities.

TTL controls when refresh is attempted; checkpoints and watermarks control what refresh reads, upserts, and reconciles.

`auto` mode MUST use TTL only to decide whether a ready index is fresh or stale. TTL MUST NOT decide source row eligibility, change detection, pruning, or incremental reconciliation.

Checkpoints and watermarks MUST remain ctx-owned metadata. They define the source state observed by successful refreshes and the boundaries used by refresh to select, upsert, and reconcile OpenCode source rows.

Failed, skipped, and running refresh attempts MUST NOT advance TTL freshness, checkpoints, or watermarks. Only a successful refresh updates successful-refresh metadata.

`--refresh off` bypasses refresh policy entirely and reads only an existing ready ctx index.

## Refresh State

Refresh state is ctx-owned metadata for a source. It records freshness, refresh lifecycle state, checkpoints, watermarks, and failure diagnostics.

Refresh state is separate from source identity. `ctx_source` identifies the OpenCode source and stores source identity/count metadata. Refresh timing, refresh status, checkpoints, watermarks, and diagnostics belong to refresh state.

For each source, refresh state MUST track:

- latest successful refresh completion time
- latest refresh attempt status
- latest refresh attempt start time
- latest refresh attempt completion time
- checkpoint observed during the latest successful refresh
- source-table watermarks required for incremental reconciliation
- latest failed refresh time and error message

TTL freshness MUST use the latest successful refresh completion time. Failed, skipped, and running attempts MUST NOT make an index fresh.

Refresh state is stored only in the ctx database. ocint MUST NOT store refresh state in or write refresh state to the OpenCode database.

## Checkpoints

The checkpoint describes the OpenCode source state observed during a successful refresh and participates in deciding what refresh reads, upserts, and reconciles.

Checkpoint data belongs to ctx-owned refresh state. ocint MUST NOT write checkpoint data to the OpenCode database.

The initial checkpoint uses source file metadata such as size and `mtime_ns`. This is enough to detect obvious source changes, but TTL remains the policy gate for auto refresh.

Refresh checkpoints MAY include source file metadata, source row counts, source-table watermarks, or other ctx-owned metadata required for incremental reconciliation.

TTL controls when refresh is attempted; checkpoints and watermarks control what refresh reads, upserts, and reconciles.

## Stale-While-Revalidate

Stale-while-revalidate is the default behavior for a ready but stale ctx index.

Foreground search MUST finish against the currently ready index. It MUST NOT block on the refresh that it schedules.

Refresh scheduling MUST happen after the foreground read transaction is closed. This avoids a foreground reader holding a transaction while the refresh worker tries to write.

The command MAY emit a quiet diagnostic in verbose mode, but normal search output MUST remain focused on search results.

## Background Refresh

Background refresh MUST outlive the foreground `ocint ctx search` process if search returns to the shell immediately.

An in-process Python thread is not sufficient for this CLI behavior. A non-daemon thread keeps the process alive; a daemon thread is killed when the process exits. Python 3.14 free-threading can help parallelize refresh internals, but it does not change process lifetime.

The background refresh implementation MUST use a detached worker process or a long-lived daemon. The initial implementation uses a detached worker process because it has fewer moving parts than introducing a daemon protocol.

### Worker

The worker runs the same refresh workflow as foreground import, but without user-facing progress rendering.

The worker MUST resolve the same ctx DB path and OpenCode source path as the command that scheduled it. Required environment variables MUST be passed explicitly when the worker is spawned.

The worker MUST write diagnostics to a ctx-owned log file or other ctx-owned diagnostic location. It MUST NOT write noisy output into the foreground search response.

### Locking

A ctx DB MUST NOT have more than one refresh running at a time.

The worker MUST acquire a non-blocking lock before refreshing. If another refresh already holds the lock, the worker exits successfully without doing work.

The lock MUST be ctx-owned and path-scoped, for example `<ctx-db>.refresh.lock`. On Linux, `fcntl.flock` is an acceptable implementation detail.

The worker MUST re-check freshness after acquiring the lock. Another process can refresh the index between scheduling and lock acquisition.

### Failures

Background refresh failures MUST NOT fail the foreground search that scheduled them.

Failures MUST be logged with enough detail to diagnose source path problems, migration errors, SQLite lock timeouts, and import exceptions.

The next default search MAY schedule refresh again if TTL still considers the index stale.

## Incremental Import

Refresh MUST avoid full delete and re-import cycles.

The current rebuild strategy clears all rows for a source and then inserts all sessions, events, file rows, and FTS rows again. That is simple and correct, but it makes every refresh expensive.

The target strategy is incremental reconciliation by stable source keys.

### Source Keys

Sessions are identified by `(source_id, provider_session_id)`.

Transcript events are identified by `(source_id, source_table, event_id)`.

File rows are identified by `(source_id, source_table, event_id, path)`.

These keys already exist in the ctx schema as unique constraints, so incremental import MUST use them rather than inventing new identity fields.

### Change Selection

Refresh MUST use ctx-owned checkpoints and watermarks to select source rows for incremental reconciliation.

TTL MUST NOT determine which source rows are read, upserted, or pruned. TTL only determines whether refresh is attempted.

Source-row selection MUST account for every OpenCode source table that contributes to the ctx projection.

### Upserts

Refresh MUST upsert sessions and events using the stable source keys.

For unchanged rows, refresh MUST avoid unnecessary writes when practical. A payload hash or comparable checkpoint MAY be added later if row-level change detection is needed.

For changed events, refresh MUST update the event row and replace dependent projections that derive from the event payload.

### Pruning

Refresh MUST eventually remove ctx rows whose source rows disappeared from OpenCode.

The preferred implementation is a seen-key reconciliation. During refresh, collect the source keys observed for the current source. After upserts complete, delete ctx rows for that source whose keys were not seen.

This avoids clearing the whole source up front while preserving deletion correctness.

### FTS

FTS rows are derived from ctx events and MUST stay in sync with event search text.

For inserted events, insert the corresponding FTS row.

For changed events, delete the old FTS row for that event primary key and insert the replacement row.

For pruned events, delete matching FTS rows before deleting the base ctx event rows when the event primary keys are still available.

### Files

File-touched rows are derived from event payloads.

For changed events, replacing file rows for that event is acceptable. Full source-wide file deletion is not required.

For pruned events, delete file rows for those event keys.

## Concurrency

Search reads and refresh writes can overlap.

The ctx SQLite connection MUST enable WAL mode for better reader and writer concurrency. It MUST also set a busy timeout so short writer conflicts can resolve without immediate failure.

Foreground search MUST NOT hold a read transaction while scheduling or waiting for refresh. The stale search MUST complete and close its session before the background worker starts writing.

Refresh writes MUST commit at safe boundaries. A failed refresh MUST NOT leave the ctx index half-updated from the perspective of later searches.

## CLI UX

Default search MUST be fast when a ready index exists.

`ocint ctx search "query"` MUST use `auto` mode.

`ocint ctx search "query" --refresh off` MUST skip all refresh behavior and read only the existing ready index.

`ocint ctx import` remains the explicit foreground refresh command. It MUST continue to show progress for human output and suppress progress for JSON output.

If default search schedules a background refresh, normal output MUST still render search results. Verbose output MAY mention that refresh was scheduled.

## Config

Refresh TTL MUST have one default source of truth.

The first supported knob is `OCINT_CTX_REFRESH_TTL`. If unset, use the default TTL.

Invalid TTL values MUST fail at the CLI boundary with a clear message. Services MUST receive parsed typed configuration, not raw strings.

Future config MAY add a background-refresh toggle, log path, or worker timeout. These MUST stay in ctx feature config rather than global application modules.

## Observability

`ocint ctx status` MUST expose refresh-relevant metadata when a ready ctx index exists.

Status output MUST include:

- latest successful refresh time
- TTL freshness state
- latest refresh attempt status
- source checkpoint summary
- whether a refresh is currently in progress
- latest refresh error, when present

Status output MAY include source-table watermarks or checkpoint details when useful for debugging.

Observability fields are diagnostic. Search correctness MUST NOT depend on diagnostic rendering.

## Non-Goals

Refresh does not make OpenCode writable.

Refresh does not require search services to import OpenCode modules directly.

Refresh does not require a long-lived daemon in the initial implementation.

Refresh does not guarantee that a stale-while-revalidate search includes the newest OpenCode history in the current command. It guarantees that a ready index can be searched immediately and refreshed for later commands.
