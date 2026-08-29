# zwm

`zwm` reconciles durable tmux sessions on the configured VM with Zed's
read-only Terminal Thread metadata, then restores the corresponding remote
worktrees in one Zed window.

## Setup

```bash
just zwm
just lch
```

`just zwm` symlinks `zwm/config.json` to `~/.config/zwm/config.json`, installs
the native macOS binary, cross-compiles the configured Linux target, verifies
the transferred artifact, and installs it on the VM.

`just lch` installs the persistent `lch-zwm` LaunchAgent that runs `zwm daemon`.

## Commands

```bash
zwm status
zwm restore --dry-run
zwm restore --latest --dry-run
zwm restore --latest
zwm list
zwm logs
zwm doctor
```

`restore --latest` reconciles current remote tmux sessions with Zed Terminal
Thread records before planning. `--dry-run` renders that same plan without
persisting it or opening Zed. `--worktree <absolute-path>` may be repeated to
limit either operation to an explicit subset.

Human-facing status and restore plans use terminal-aware styling. Styling is
automatically disabled for redirected output, `NO_COLOR`, and `TERM=dumb`.

Zed evaluates the shell initializer from `zwm terminal-init-command-session`:

```json
"terminal_init_command": "eval \"$(zwm terminal-init-command-session)\""
```

The resolver reads no database. It derives a deterministic tmux session name
from the absolute Git worktree root and prints shell code. Zed's original shell
evaluates that code to create or attach the worktree's durable tmux session and
repair `@zwm_worktree` metadata omitted by a Continuum restore.

## Verification

```bash
just --justfile bin/zwm/justfile test
bin/zwm/scripts/terminal-init-check.sh
bin/zwm/scripts/restore-check.sh
```

The scripts only inspect Zed's database read-only. `restore-check.sh --apply`
runs the real Zed restoration sequence.
