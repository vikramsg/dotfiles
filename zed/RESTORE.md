# Reopen VM Worktree Terminals

Zed stores Agent Panel state per workspace.

```text
zed -n ssh://vm-us:/home/vikram_orbio_earth/projects/orbio/meanderx/kunda
```

`-n` opens `kunda` in a new Zed window.

```text
zed -r ssh://vm-us:/home/vikram_orbio_earth/projects/orbio/meanderx/kunda-wt
zed -r ssh://vm-us:/home/vikram_orbio_earth/projects/orbio/meanderx/kunda-wt2
```

`-r` reuses a Zed window for the same remote identity and opens each path as
another workspace. With AI enabled, Zed retains the workspaces in the
multi-workspace window.

```text
kunda
kunda-wt
kunda-wt2
```

When a worktree workspace opens, Zed loads its Agent Panel state.

## Restore A Saved Terminal

If both values exist:

```text
last_active_terminal_id = <terminal ID>
sidebar_terminal_threads contains <terminal ID>
```

Zed creates a fresh frontend for that same saved Terminal Thread ID.

## Create A New Terminal Frontend

If the workspace remembers:

```text
last_created_entry_kind = Terminal
```

Zed creates a new Terminal Thread when its Agent Panel activates. This works
even when `last_active_terminal_id` is null or its old metadata is missing.

The new terminal uses the worktree working directory and runs
`agent.terminal_init_command`. A command that derives its tmux session name
from the working directory attaches the new Zed frontend to the persistent
session for that worktree.
