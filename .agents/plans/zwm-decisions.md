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

## Go Project Layout

ZWM is a Go command organized as cohesive capability packages. The executable
entry point is isolated under `cmd/`; non-public code is under `internal/`.

```text
bin/zwm/
├── go.mod
├── go.sum
├── README.md
├── cmd/
│   └── zwm/
│       └── main.go
├── internal/
│   ├── app/
│   │   └── app.go
│   ├── cli/
│   │   ├── cli.go
│   │   └── cli_test.go
│   ├── config/
│   │   ├── config.go
│   │   └── config_test.go
│   ├── inventory/
│   │   ├── record.go
│   │   ├── reconcile.go
│   │   ├── reconcile_test.go
│   │   └── testdata/
│   ├── terminal/
│   │   ├── init.go
│   │   ├── init_test.go
│   │   └── testdata/
│   ├── restore/
│   │   ├── restore.go
│   │   └── restore_test.go
│   ├── state/
│   │   ├── store.go
│   │   ├── events.go
│   │   └── store_test.go
│   ├── zed/
│   │   ├── reader.go
│   │   └── opener.go
│   └── tmux/
│       └── client.go
└── scripts/
    ├── terminal-init-check.sh
    └── restore-check.sh
```

| Package | Owns |
|---|---|
| `cmd/zwm` | Process entry point only. Calls `app.New()` and exits with the resulting status. |
| `app` | Application assembly: loads configuration, creates concrete dependencies, and wires CLI commands. |
| `cli` | Argument parsing and rendering command results. It does not contain reconciliation rules. |
| `config` | ZWM configuration and validation. |
| `inventory` | ZWM session records and reconciliation rules between tmux inventory and Zed terminal/worktree records. |
| `terminal` | `zwm terminal-init-command`: resolve, create, and attach the appropriate ZWM tmux session. |
| `restore` | Turn the latest valid inventory into Zed workspace-open requests. |
| `state` | Persisted ZWM inventory, reconciliation timestamps, and event log. |
| `zed` | Read Zed state read-only and invoke Zed to open workspaces. |
| `tmux` | Inspect and operate ZWM-managed tmux sessions. |

Each package defines the small interfaces it consumes. There is no central
`ports` package. The project does not start with generic `pkg`, `common`,
`helpers`, `utils`, `models`, `domain`, `adapters`, or `testutils`
directories.

Unit tests are colocated with the package under test. Static fixtures are kept
in that package's `testdata/` directory. The noninteractive real-environment
compatibility scripts are kept in `bin/zwm/scripts/`.

## Go Libraries

ZWM uses established Go packages for standard infrastructure rather than
hand-building a command parser, SQLite driver, logger, test assertion library,
or UUID implementation. The direct dependency set stays deliberately small.

| Need | Package | Use |
|---|---|---|
| CLI commands and flags | `github.com/spf13/cobra` | Command tree for `daemon`, `reconcile`, `restore`, `terminal-init-command`, `status`, `list`, `logs`, and `doctor`. |
| SQLite access | `database/sql` and `modernc.org/sqlite` | Read-only Zed database access without CGO requirements. |
| Structured application logging | `log/slog` | Structured ZWM event logging. |
| Command execution | `os/exec` | `ssh`, `tmux`, and `zed` execution at real system boundaries only. |
| Daemon lifecycle | `context`, `os/signal`, and `syscall` | Cancellation and controlled daemon shutdown. |
| Filesystem and paths | `path/filepath`, `os`, and `io/fs` | Local configuration and state access. |
| Session ID generation | `crypto/rand` and `encoding/hex` | Opaque session IDs without a UUID dependency. |
| Zed metadata decoding | `encoding/json` | Decode Zed JSON metadata. |
| Unit tests | `testing` | Standard Go testing framework. |
| Semantic test comparisons | `github.com/google/go-cmp/cmp` | Compare structured values without rendered-output snapshots. |
| Optional property tests | `testing/quick` | Property tests for durable rules such as session-name parsing. |

The expected direct dependencies are:

```text
github.com/spf13/cobra
modernc.org/sqlite
github.com/google/go-cmp
```

ZWM does not add `viper`, `testify`, `sqlmock`, `mockery`, `zap`, `zerolog`,
`afero`, `urfave/cli`, or `google/uuid` without an approved requirement.

ZWM's own persisted-state format remains undecided. If configuration needs
TOML, use `github.com/pelletier/go-toml/v2`; if it needs JSON, use
`encoding/json`; if it needs SQLite, reuse `database/sql` and
`modernc.org/sqlite`. The state-format decision precedes adding any additional
dependency.

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
a minimal set of noninteractive scripts in `bin/zwm/scripts/`. These scripts
are not part of the unit-test suite.

The integration checks cover:

- terminal initialization: real Zed invokes `zwm terminal-init-command`, which
  creates or attaches to a real ZWM tmux session on the VM;
- restoration: a real Zed/VM/tmux/LCH environment restores the recorded
  worktrees and reattaches replacement Zed Terminal Threads to their durable
  tmux sessions.

These scripts are compatibility checks for installed versions and environment
configuration. They are run for relevant Zed, ZWM, LCH, SSH, or terminal-init
changes, rather than being expanded into a broad integration test suite.

## Review Discipline

This decision record is authoritative during implementation. A review
sub-agent supplies evidence; it does not decide product scope or redesign the
solution.

Every review request must constrain findings to:

```text
- violations of this decision record;
- defects that prevent an agreed command or acceptance criterion from working;
- safety violations, especially writing to Zed's database;
- regressions against an existing repository convention.
```

Reviewers must not recommend new commands, flags, workflows, configuration,
generic packages, abstractions, compatibility layers, retry/fallback behavior,
or broader tests based only on hypothetical future requirements. They must
classify every finding as one of:

1. Direct decision-record violation.
2. Demonstrable correctness or safety bug.
3. Optional improvement outside scope.

| Review finding | Implementation response |
|---|---|
| Direct decision-record violation | Fix it. |
| Demonstrable bug in an agreed behavior | Fix it. |
| Existing repository rule is violated | Fix it. |
| Requires changing commands, package layout, testing boundary, persistence policy, or Zed/tmux behavior | Ask for approval before changing scope. |
| Generic defensive suggestion without an observed failure mode or decision-record requirement | Do not adopt it. |
| “Could be useful later” abstraction or compatibility code | Do not adopt it. |

Implementation reviews must preserve these boundaries:

```text
- No CLI flags beyond the documented command surface.
- No manual registration, per-worktree restore, per-session restore, --live, or forget.
- No Zed database writes.
- No generic domain/adapter/ports/helper layer.
- No real Zed, SSH, tmux, LCH, shell, or SQLite-file execution in unit tests.
- No expansion of the two compatibility scripts into an integration suite.
- No remote-side behavior beyond zwm terminal-init-command without approval.
```

Before completion, implementation is checked against this decision-record
checklist:

```text
[ ] Package layout matches the documented Go structure.
[ ] Each command matches the documented command table.
[ ] Local-only commands do not independently inspect the VM.
[ ] Daemon, reconcile, and doctor use VM plus local Zed state as specified.
[ ] Terminal initialization is owned by zwm terminal-init-command.
[ ] Zed database access is read-only.
[ ] Unit tests meet the acceptance criteria.
[ ] Real-environment checks remain only in bin/zwm/scripts/.
```

## Explicitly Not Decided

- Binary language, package location, and storage format.
- Reconciliation interval and retry/backoff policy.
- Exact LCH service identifier and configuration changes.
- Exact Zed setting string and terminal-init create/attach algorithm.
- Ambiguous-match handling beyond recording and reporting the condition.
