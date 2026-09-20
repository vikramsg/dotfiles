# Archive

Packages removed from active use, kept for reference. Original repo paths are preserved under this
directory so a moved file's provenance is readable from its location.

---

## `bin/ghostty_workspace/`, `ghostty/workspaces/`

Archived 2026-09-20.

`ghostty-workspace` opened a Ghostty window with tabs, commands and directories read from a TOML file
under `~/.config/ghostty/workspaces/`. Every workspace file defined its remote tabs as
`/opt/homebrew/bin/autossh ...`, an absolute path that does not exist on the Intel Mac running this
repo (Homebrew is at `/usr/local`). The tabs therefore never started.

The tool and its configurations moved together, because `ghostty-workspace` had no other config source.

## `zwm/`, `bin/zwm/`

Archived 2026-09-20.

`zwm` reconciled Zed worktree windows against durable tmux sessions. It also supplied the
`terminal-init-command-session` initializer that Zed's `agent.terminal_init_command` called to attach
each integrated terminal to its worktree's tmux session.

The binary was not installed on this host — neither `~/.local/bin/zwm` nor `~/go/bin/zwm` exists, and the
`lch-zwm` launchd service was exiting with status 1 — so the workflow was already non-functional.

The Zed auto-attach behaviour is preserved by a self-contained snippet in `zed/settings.json` that derives
the same deterministic session name from the Git worktree root. See
`.agents/plans/brewfile-to-mise.md`.

## `hunk-zsh-migration.md`

Archived 2026-09-20.

A plan to migrate the `bin/hunk-review` launcher into `zsh/.zsh_script` as a shell function. Superseded:
`hunk` itself was removed from this repo, so the launcher the plan described no longer exists.
