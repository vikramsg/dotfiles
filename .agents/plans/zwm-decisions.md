# ZWM Decisions: What

This is a product-decision record, not an implementation plan.

## Purpose

`zwm` restores a Zed window containing the Zed Terminal Threads represented by
currently running ZWM-managed tmux sessions across remote worktrees.

All Terminal Threads in scope are opened through ZWM's tmux terminal workflow.
The tmux session is the durable session; the Zed Terminal Thread is the
frontend recreated during restoration.

## Session Identity

ZWM-managed tmux sessions use this name format:

```text
zwm-v1-<session-id>-<parent>-<leaf>
```

Example:

```text
zwm-v1-7aef9c52-meanderx-kunda-wt
```

- `zwm-v1` identifies ZWM ownership and the naming-schema version.
- `<session-id>` is the unique durable tmux-session identifier.
- `<parent>` and `<leaf>` are human-readable reconciliation hints.
- The complete worktree path is not encoded in the tmux session name.

The canonical remote worktree path comes from Zed's database, not from parsing
the tmux session name.

## Terminal Initialization

Terminal initialization is part of ZWM's scope. Zed's
`agent.terminal_init_command` runs on the VM and invokes:

```text
zwm terminal-init-command
```

That ZWM subcommand runs in the worktree working directory supplied by Zed. It
resolves the existing ZWM tmux session for that worktree or creates one, then
attaches the Terminal Thread to it. It owns creation of the ZWM tmux session
name and replaces the current shell-only `zed-<parent>-<leaf>` initialization.

ZWM must therefore be available on the VM for terminal initialization, in
addition to the local ZWM process managed by LCH.

## Reconciliation

ZWM periodically reconciles two sources:

```text
VM tmux inventory
  -> live ZWM-managed tmux session names and IDs

Local Zed database, read-only
  -> remote identity, Terminal Thread metadata, and canonical working directory
```

The reconciliation binds a tmux session ID to the matching canonical Zed
worktree path. ZWM persists that binding in its own local state so it remains
available after Zed removes Terminal Thread metadata during a disconnect.

ZWM never writes to Zed's database.

## Service Lifecycle

ZWM runs as a persistent local service managed by LCH. It is not a timer-driven
or one-shot OCINT-style daemon job.

```text
LCH persistent service
  -> zwm daemon
  -> periodic remote tmux scan + local Zed-database reconciliation
```

## Command Surface

| Command / flag | Purpose | Information required |
|---|---|---|
| `zwm daemon` | Persistent LCH-managed reconciliation service. | Remote VM + local DB |
| `zwm reconcile` | Run one reconciliation pass immediately. | Remote VM + local DB |
| `zwm terminal-init-command` | Zed-invoked remote terminal initializer. Resolve/create the worktree's ZWM tmux session and attach to it. | Remote VM only |
| `zwm list` | List persisted reconciled sessions and worktrees. | Local DB only |
| `zwm status` | Show tracker state, latest scan, counts, and failures. | Local DB only |
| `zwm restore` | Reopen all worktrees from the latest successful reconciliation. | Local DB only for selection; Zed connects to the VM while opening workspaces |
| `zwm restore --new-window` | Restore into a new Zed window. | Local DB only for selection |
| `zwm restore --reuse-window` | Restore into an existing compatible Zed window. | Local DB only for selection |
| `zwm restore --dry-run` | Show planned Zed opens without opening them. | Local DB only |
| `zwm logs` | Show recent ZWM actions, no-ops, skips, failures, and restore attempts. | Local DB only |
| `zwm logs --lines <count>` | Set the number of recent log entries. | Local DB only |
| `zwm logs --follow` | Stream new local ZWM log entries. | Local DB only |
| `zwm doctor` | Verify local state, LCH, SSH, tmux, and reconciliation prerequisites. | Remote VM + local DB |

The interface deliberately has no manual registration, individual-worktree
restore, individual-session restore, `--live` variants, or `forget` command.

## Record Provenance

Every command that shows persisted data must identify its source and timestamp.
At minimum, reconciled-session records show:

```text
source: zwm local state
recorded_at: <timestamp>
last_seen_on_vm_at: <timestamp>
last_matched_to_zed_at: <timestamp>
zed_database_observed_at: <timestamp>
```

`zwm status` shows when the displayed state was last successfully reconciled
and whether a later reconciliation failed.

## Logs

`zwm logs` reports the latest actions and non-actions taken by ZWM, including:

- successful reconciliations;
- unchanged/no-op scans;
- discovered sessions;
- skipped or unresolved reconciliations;
- remote connectivity failures;
- restoration attempts and outcomes.

Each log entry has a timestamp. Logs describe the latest known result even when
the binary could not act.

## Acceptance Criteria

### Unit Tests

The retained unit-test suite verifies ZWM's domain behavior only. Unit tests do
not execute `zed`, `ssh`, `tmux`, `launchctl`, `lch`, shell commands, or real
SQLite files.

External state is represented by narrow in-memory fakes for the tmux inventory,
Zed terminal state, ZWM state store, clock, event log, and workspace opener.
Tests do not mock or assert private implementation call sequences.

The unit suite must verify these durable contracts:

- session-name acceptance and rejection for the ZWM naming schema;
- reconciliation of remote identity and canonical worktree paths;
- rejection of ambiguous matches rather than incorrect mappings;
- preservation of the last successful inventory after a failed reconciliation;
- restore planning from the latest valid inventory;
- required record provenance and timestamps in status and list data;
- event logging for success, no-op, unresolved, failure, and restore outcomes;
- terminal-init decisions to attach an existing session or create a new one.

Unit tests assert semantic state and behavior, not complete rendered-output
snapshots, command text, or database dumps. They use fixed clocks and IDs, have
no sleeps or ordering dependencies, and each must fail for a plausible broken
behavior rather than an internal refactor.

### Manual Integration Checks

Real Zed, SSH, tmux, LCH, shell commands, and VM behavior are validated only by
a minimal set of noninteractive scripts in `scripts/`. These scripts are not
part of the unit-test suite.

The integration checks cover:

- terminal initialization: real Zed invokes `zwm terminal-init-command`, which
  creates or attaches to a real ZWM tmux session on the VM;
- restoration: a real Zed/VM/tmux/LCH environment restores the recorded
  worktrees and reattaches replacement Zed Terminal Threads to their durable
  tmux sessions.

These scripts are compatibility checks for installed versions and environment
configuration. They are run for relevant Zed, ZWM, LCH, SSH, or terminal-init
changes, rather than being expanded into a broad integration test suite.

## Explicitly Not Decided

- Binary language, package location, and storage format.
- Reconciliation interval and retry/backoff policy.
- Exact LCH service identifier and configuration changes.
- Exact Zed setting string and terminal-init create/attach algorithm.
- Ambiguous-match handling beyond recording and reporting the condition.
