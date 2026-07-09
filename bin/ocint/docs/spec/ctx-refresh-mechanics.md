# ctx Refresh Mechanics

## Purpose

This document records the concrete `ocint ctx` refresh implementation mechanics. The behavioral spec lives in `ctx-refresh.md`.

## Mental Model

Search reads the ctx-owned SQLite index. Refresh updates that index from the read-only OpenCode SQLite source.

Default `auto` search uses stale-while-revalidate: a ready stale index is searched first, then a background worker refreshes for later commands. `--refresh off` is deterministic index-only behavior.

## Path Identity

### Ctx DB Path

`resolve_ctx_db_path(...)` canonicalizes the ctx DB path at the ctx boundary. The canonical path is used for migrations, ctx sessions, locks, logs, and worker handoff.

### Source DB Path

`resolve_ctx_source_db_path(...)` canonicalizes the OpenCode source DB path at the ctx boundary. The canonical path is used for `ctx_source.source_path`, refresh-state lookup, `OpenCodeRepository`, and worker handoff.

### Alias Protection

`reject_ctx_source_db_alias(...)` rejects configurations where the ctx DB aliases the OpenCode source DB. The guard runs before `ctx_session(...)`, `migrate_ctx_db(...)`, readiness checks, or ctx SQLite pragmas.

### Worker Environment

The scheduler passes canonical paths to the worker through:

```text
OCINT_CTX_DB=<canonical ctx db path>
OPENCODE_DB=<canonical source db path>
```

## Refresh Decision Flow

### `auto`

`auto` refresh decisions are source-specific. Freshness is computed from the current source's refresh state, not from aggregate state across all imported sources.

- Missing or unready ctx index: foreground refresh, then search.
- Ready and fresh current-source index: search only.
- Ready but stale current-source index: search first, then schedule a worker.

### `off`

`off` reads only an existing ready ctx index. It does not parse TTL config, migrate, import, or schedule a worker.

## Foreground Refresh

Foreground refresh is used by `ocint ctx import` and default search when there is no ready current-source index.

```text
resolve canonical ctx/source paths
reject ctx/source alias
resolve refresh config
acquire ctx refresh lock
migrate ctx DB under lock
commit running attempt state
run incremental import
commit success state
release lock
```

If refresh fails after attempt state exists, import writes roll back and failure metadata is recorded in a separate transaction. The last successful refresh state, checkpoint, and watermarks are preserved.

## Background Worker

The worker is scheduled only after foreground search has rendered results and closed its read session.

### Launch Command

`schedule_refresh_worker(...)` starts the hidden command as a detached process:

```python
[sys.executable, "-c", "from ocint.cli import main; main()", "ctx", "refresh-worker"]
```

### Lock Behavior

The lock path is derived from the canonical ctx DB path:

```text
<canonical ctx db>.refresh.lock
```

The `.refresh.lock` file is only the coordination file. The actual lock is the kernel `flock` held on the open file descriptor, not the file's existence on disk. The lock file may remain after refresh completes.

ocint opens the file and requests an exclusive, non-blocking advisory lock:

```python
fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
```

If another process already holds the lock, the call fails immediately instead of waiting.

- Foreground `ctx import` lock contention fails visibly.
- Hidden worker lock contention exits successfully without work.
- The lock is released when ocint unlocks and closes the file descriptor, or automatically if the process exits.
- The lock covers migration, freshness re-check, attempt state, import, and success/failure state.

### Freshness Recheck

After acquiring the lock and completing migration, the worker re-checks current-source freshness. If another process already made the source fresh, the worker exits without importing.

### Logs

Scheduler and worker diagnostics are JSON Lines written to:

```text
<canonical ctx db>.refresh.log
```

The scheduler appends `refresh_worker_scheduled` and `refresh_worker_spawned` records. The detached worker writes structured lifecycle, decision, progress, success, skip, and failure records to stdout, and stdout/stderr are redirected to the same log file.

Example records:

```jsonl
{"event":"refresh_worker_spawned","level":"info","pid":581825,"ctx_db":"/home/user/.local/state/ocint/ctx.sqlite","source_db":"/home/user/.local/share/opencode/opencode.db","ts":"2026-07-08T12:00:00.000Z"}
{"event":"refresh_decision","level":"info","pid":581825,"action":"foreground_refresh","freshness":"stale","ttl_ms":3600000,"ts":"2026-07-08T12:00:00.100Z"}
{"event":"import_progress","level":"info","pid":581825,"message":"Writing events","current":5000,"total":238886,"ts":"2026-07-08T12:00:01.000Z"}
{"event":"refresh_succeeded","level":"info","pid":581825,"events_seen":238886,"events_written":42,"duration_ms":8950,"ts":"2026-07-08T12:00:09.000Z"}
```

Foreground search output remains focused on search results. JSON command output must remain valid JSON only.

## Refresh State

Refresh state is stored in ctx-owned `ctx_refresh_state`, keyed by `ctx_source.id`.

### Source Identity

`ctx_source` owns source identity and counts only:

- provider
- source type
- canonical source path
- session/event counts

`ctx_source` does not own refresh timestamps or checkpoints. `ctx_sources.imported_at` is derived from `ctx_refresh_state.latest_success_completed_at`.

### State Transitions

`running`:

```text
latest_attempt_status=running
latest_attempt_started_at=<attempt start>
latest_attempt_completed_at=NULL
```

`success`:

```text
latest_attempt_status=success
latest_attempt_completed_at=<completion>
latest_success_started_at=<attempt start>
latest_success_completed_at=<completion>
latest_success_checkpoint_payload=<checkpoint>
source_watermark_payload=<watermarks>
latest_error_message=NULL
```

`failed`:

```text
latest_attempt_status=failed
latest_attempt_completed_at=<completion>
latest_failed_at=<completion>
latest_error_message=<truncated error>
latest_success_* unchanged
checkpoint/watermarks unchanged
```

## Incremental Reconciliation

Refresh avoids source-wide clear/re-import.

```text
scan source session keys
scan source session_message keys
scan source message/part event keys
load existing ctx fingerprints
classify new/changed/unchanged/pruned rows
fetch full payloads only for changed, new, or reprojected rows
upsert changed/new sessions
upsert changed/new/reprojected events
replace FTS rows for affected event primary keys
replace file rows for affected event keys
prune missing events
prune missing sessions
update source counts
record success checkpoint/watermarks
```

If a source session row disappears while message/part rows remain, affected events are reprojected with `session=None` before session pruning. This removes stale session title/workspace terms from `ctx_event.search_text` and replaces the affected FTS rows while preserving event primary keys.

## Status And Observability

`ocint ctx status` reads persisted ctx metadata and does not require the current source DB to exist.

Status exposes:

- TTL and freshness
- refresh in-progress state from the lock
- latest attempt, success, and failure fields
- checkpoint summary
- top-level source provenance
- per-source refresh metadata

Top-level refresh fields come from one selected source status; they do not mix success, attempt, and failure rows from different sources.

## Troubleshooting

### Search Is Stale

A ready stale search intentionally returns existing-index results first. The scheduled worker refreshes the index for later commands.

### Worker Did Not Run

The worker exits without import when the lock is held or the post-lock freshness re-check finds the source is already fresh.

### Refresh Failed

Foreground refresh reports the failure. Background refresh writes diagnostics to the ctx refresh log and records failure metadata when refresh state is available.

### JSON Output Must Stay Clean

Progress, diagnostics, worker logs, and scheduling messages must not be emitted into JSON stdout.

## Verification

Manual refresh verification uses a non-home source DB:

```bash
export OPENCODE_DB="/tmp/opencode/source_opencode.db"
export OCINT_CTX_DB="/tmp/opencode/ocint-ctx-refresh-manual.sqlite"
export OCINT_CTX_REFRESH_TTL="1h"
```

Use default search to exercise foreground import, repeated search for fresh-index behavior, `OCINT_CTX_REFRESH_TTL=0` for stale-while-revalidate, `--refresh off` for index-only behavior, and `ocint ctx status` for refresh metadata.
