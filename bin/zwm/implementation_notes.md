# ZWM Implementation Notes

## Decisions Applied

- ZWM is a Go command in `bin/zwm`; its active configuration is external at
  `~/.config/zwm/config.json`, symlinked from `zwm/config.json` by `just zwm`.
- The initial configured remote host is `vm-us`.
- `just zwm` delegates to `bin/zwm/justfile`. The package justfile keeps local
  build, remote platform discovery, cross-compilation, transfer, and remote
  installation as separate recipes.
- The package justfile builds the remote Linux binary on the Mac. The VM does
  not need Go installed. It uses resumable compressed `rsync` for the remote
  artifact transfer because the configured SSH path stalls on large `scp`
  transfers. The recipe verifies a SHA-256 checksum before atomically replacing
  the remote binary.
- ZWM session IDs are the first eight lowercase hexadecimal characters of the
  SHA-256 hash of the normalized absolute Git worktree root. A collision uses
  the first 16 characters and records the normalized root in tmux
  `@zwm_worktree` metadata.
- The terminal hook has no database dependency. It derives the worktree root,
  selects the deterministic session name, and prints a shell initializer. Zed's
  original shell evaluates that initializer and performs tmux creation and
  attachment directly. On Linux it uses the same Linuxbrew tmux binary as the
  running server and repairs `@zwm_worktree` on existing Continuum sessions.
- Zed database access uses SQLite read-only mode and `PRAGMA query_only = ON`.
- ZWM state is separate SQLite at `$XDG_STATE_HOME/zwm/zwm.sqlite`, defaulting
  to `~/.local/state/zwm/zwm.sqlite`. It is never deleted by ZWM.
- `lch-zwm` runs `zwm daemon`. Reconciliation runs every 10 minutes. A failed
  scan logs a failure and preserves the prior successful inventory until the
  next scheduled scan.
- LCH LaunchAgent services need `~/.local/bin` in their inherited `PATH` so the
  configured `zwm` command resolves after installation. The existing launchd
  service path now includes it.
- `restore --latest` reconciles current tmux and Zed inventory immediately;
  its dry run renders the same plan without persisting or opening Zed.
- Status and restore plans share a Lip Gloss renderer. Interactive terminals
  receive styled output, narrow terminals receive stacked restore fields, and
  redirected output, `NO_COLOR`, and `TERM=dumb` remain ANSI-free.
- Restore opens the first worktree with `zed -n`, then remaining worktrees with
  `zed -r`, waiting three seconds between requests.
- Unit tests use fakes and isolated temporary state stores. They never execute
  Zed, SSH, tmux, LCH, or the real Zed/ZWM databases. Real-environment checks
  stay in `bin/zwm/scripts/`.
- `terminal-init-check.sh` reads Zed's SQLite database in read-only mode,
  inspects live remote tmux sessions, and then runs read-only ZWM status.
  `restore-check.sh` is dry-run by default; its explicit `--apply` mode performs
  the documented Zed restoration sequence.

## Verification Observation

Non-interactive SSH originally resolved Ubuntu tmux 3.4 while the live server
was Linuxbrew tmux 3.7c, producing the misleading client error `server exited
unexpectedly`. ZWM now selects `/home/linuxbrew/.linuxbrew/bin/tmux` for remote
inventory and Linux terminal initialization. Manual acceptance verified latest
dry run, live status, and the three Kunda Zed workspaces with attached terminals.
