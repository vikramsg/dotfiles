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
- `<session-id>` is the first eight lowercase hexadecimal characters of the
  SHA-256 hash of the normalized absolute Git worktree root.
- `<parent>` and `<leaf>` are human-readable reconciliation hints.
- The complete worktree path is not encoded in the tmux session name.

The terminal hook derives the normalized root with `git -C "$PWD" rev-parse
--show-toplevel` and POSIX path cleaning. Local ZWM applies the same path
normalization to Zed's recorded worktree directory, hashes it, and matches the
result to the tmux session ID. Zed's path is authoritative; terminal titles are
not part of the ZWM identity model.

ZWM creates one durable tmux session per worktree. If an eight-character hash
collision is detected for distinct normalized roots, ZWM uses the first 16 hash
characters for the colliding session and records the condition. ZWM stores the
normalized root in the tmux `@zwm_worktree` session option so the hook can
distinguish an existing worktree session from a collision.

## Terminal Initialization

Terminal initialization is part of ZWM's scope. Zed's
`agent.terminal_init_command` runs on the VM and invokes:

```text
zwm terminal-init-command
```

That ZWM subcommand runs in the worktree working directory supplied by Zed. It
derives the deterministic session ID and session name, then prints a complete
shell initializer. Zed evaluates that initializer in its original shell, which
creates or finds the tmux session, records `@zwm_worktree`, sets the title, and
execs tmux attachment. It replaces the current shell-only
`zed-<parent>-<leaf>` session-name derivation.

`zwm terminal-init-command` does not read Zed's database, ZWM's SQLite state,
or LCH configuration. It only uses its current worktree directory and the VM's
tmux server. It prints only shell code on stdout; it does not create or attach
tmux itself.

ZWM must therefore be available on the VM for terminal initialization, in
addition to the local ZWM process managed by LCH.

Zed invokes the hook with this setting:

```json
"terminal_init_command": "eval \"$(zwm terminal-init-command-session)\""
```

## Reconciliation

ZWM periodically reconciles two sources:

```text
VM tmux inventory
  -> live ZWM-managed tmux session names and IDs

Local Zed database, read-only
  -> remote identity, Terminal Thread metadata, and canonical working directory
```

The reconciliation hashes the normalized Zed worktree path and binds the
matching tmux session ID to that path. ZWM persists that binding in its own
local state so it remains available after Zed removes Terminal Thread metadata
during a disconnect.

Every live ZWM tmux session remains eligible for restoration. ZWM does not
classify whether Zed lost the corresponding Terminal Thread through a
disconnect, restart, or intentional close.

ZWM never writes to Zed's database.

## Service Lifecycle

ZWM runs as a persistent local service managed by LCH. It is not a timer-driven
or one-shot OCINT-style daemon job. The daemon reconciles every 10 minutes.
After a reconciliation failure, it retains the last successful inventory, logs
the failure, and retries at the next scheduled cycle without immediate retry or
backoff behavior.

```text
LCH persistent service
  -> zwm daemon
  -> periodic remote tmux scan + local Zed-database reconciliation
```

The LCH service definition is:

```toml
[services.lch-zwm]
command = ["zwm", "daemon"]
```

LCH derives the persistent service label:

```text
com.vikramsg.dotfiles.lch-zwm
```

LCH lifecycle remains owned by `just lch`, not `just zwm`.

## Go Project Layout

ZWM is a Go command organized as cohesive capability packages. The executable
entry point is isolated under `cmd/`; non-public code is under `internal/`.

ZWM configuration follows the repository's configuration pattern and is not
part of the implementation package:

```text
zwm/config.json
  -> ~/.config/zwm/config.json
```

The initial configuration contains the one supported remote host:

```json
{
  "host": "vm-us"
}
```

```text
bin/zwm/
├── go.mod
├── go.sum
├── README.md
├── justfile
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

The package justfile separates local build, remote platform discovery,
cross-compilation, remote copy, and remote installation into individual
recipes. The top-level `just zwm` recipe creates the active configuration
symlink and delegates installation to the package justfile.

`just zwm` reads the configured host, discovers the VM platform with `ssh` and
`uname`, cross-compiles a Linux binary on the Mac, and installs it at
`~/.local/bin/zwm` on the configured VM. It also installs the native local
binary at `~/.local/bin/zwm`. The VM does not need Go installed.

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
| Session ID derivation | `crypto/sha256` and `encoding/hex` | Deterministic eight-character worktree-path hash. |
| Zed metadata and ZWM configuration decoding | `encoding/json` | Decode Zed JSON metadata and `zwm/config.json`. |
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

ZWM's own persisted state uses a separate local SQLite database at
`$XDG_STATE_HOME/zwm/zwm.sqlite`, defaulting to
`~/.local/state/zwm/zwm.sqlite`. It is implemented with `database/sql` and
`modernc.org/sqlite`. ZWM never deletes that database or Zed's database.

## Command Surface

| Command / flag | Purpose | Information required |
|---|---|---|
| `zwm list` | List persisted reconciled sessions and worktrees. | Local DB only |
| `zwm status` | Show live inventory, persisted mappings, daemon state, and reconciliation freshness. | Remote VM + local DB |
| `zwm restore` | Reopen all worktrees from the latest successful reconciliation. | Local DB only for selection; Zed connects to the VM while opening workspaces |
| `zwm restore --latest` | Reconcile current tmux and Zed inventory, persist it, and restore it. | Remote VM + local DB |
| `zwm restore --new-window` | Restore into a new Zed window. | Local DB only for selection |
| `zwm restore --reuse-window` | Restore into an existing compatible Zed window. | Local DB only for selection |
| `zwm restore --dry-run` | Render the same restore plan without persisting or opening Zed. | Depends on persisted or `--latest` source |
| `zwm logs` | Show recent ZWM actions, no-ops, skips, failures, and restore attempts. | Local DB only |
| `zwm logs --lines <count>` | Set the number of recent log entries. | Local DB only |
| `zwm logs --follow` | Stream new local ZWM log entries. | Local DB only |
| `zwm doctor` | Verify local state, LCH, SSH, tmux, and reconciliation prerequisites. | Remote VM + local DB |

Daemon reconciliation and terminal initialization are hidden integration
commands. `--worktree <absolute-path>` may be repeated to scope a restore.

`zwm restore` opens the first workspace with `zed -n`, then each remaining
workspace with `zed -r`, waiting three seconds between open requests. The delay
is internal MVP behavior, not a user-facing flag or configuration setting.

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

`vm-us` is the currently confirmed real test VM. A noninteractive SSH check
with BatchMode authentication succeeded on 2026-08-28. The compatibility
scripts use this host for their real-environment checks; connectivity alone is
not accepted as proof that terminal initialization or restoration works.

#### Zed Database Observation Rule

ZWM and its compatibility scripts use Zed's database only as a read-only
observation source. They do not seed, insert, update, delete, reset, copy over,
or otherwise mutate Zed database state. They do not use a test-only Zed action
driver to manufacture Terminal Thread state.

Zed database records verify only facts Zed itself persisted, including
workspace identity, remote connection, working directory, terminal metadata,
`last_active_terminal_id`, and `last_created_entry_kind`. If a required fact is
not observable in Zed's database, ZWM verifies it from another read-only source
such as VM tmux state, or reports it as unobserved.

The integration checks cover:

- terminal initialization: inspect Zed-persisted Terminal Thread state and the
  matching real ZWM tmux session after Zed's normal terminal workflow runs;
- restoration: inspect the persisted ZWM inventory and planned restoration;
  `restore-check.sh --apply` runs the real Zed/VM/tmux/LCH restoration sequence.

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

No remaining product decisions block the MVP implementation.
