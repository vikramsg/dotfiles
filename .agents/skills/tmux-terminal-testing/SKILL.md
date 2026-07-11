---
name: tmux-terminal-testing
description: Use tmux for manual terminal testing of CLI and TUI behavior. Use when validating real TTY rendering, ANSI styling, wrapping at different widths, interactive output, progress displays, or long-running terminal commands.
---

# tmux Terminal Testing

Use tmux as an isolated real terminal when pipes, captured subprocess output, or
unit tests cannot validate the human experience. This skill is for manual
acceptance testing, not for replacing automated tests.

## Safety Rules

- Inspect existing tmux resources before creating anything.
- Create a dedicated window in an existing session when possible. Create a new
  session only when no suitable session exists.
- Record the returned session, window, and pane IDs immediately. Target stable
  IDs instead of ambiguous names or indexes.
- Kill only resources created for the test. Never use `tmux kill-server` and
  never kill a pre-existing session, window, or pane.
- Use a dedicated working directory and test data. Do not mutate production
  data or delete files that project rules prohibit deleting.
- Do not expose secrets in commands, pane captures, or reports.

## Preflight

Confirm tmux is available and record the initial state:

```bash
tmux -V
tmux list-sessions -F '#{session_id} #{session_name}'
tmux list-windows -a -F '#{session_id} #{window_id} #{window_name}'
```

If already inside tmux, identify the current resource without assuming its
name:

```bash
tmux display-message -p '#{session_id} #{window_id} #{pane_id} #{window_width}x#{window_height}'
```

## Create An Isolated Terminal

Prefer a new window in an existing session. Print and record its stable IDs:

```bash
tmux new-window -d -P -F '#{session_id} #{window_id} #{pane_id}' \
  -t <existing-session-id> -n <unique-test-name> -c <working-directory>
```

If no tmux session exists, create and own a detached session:

```bash
tmux new-session -d -P -F '#{session_id} #{window_id} #{pane_id}' \
  -s <unique-test-name> -c <working-directory>
```

Use a unique name containing the feature or command under test. Do not reuse a
window that contains user work.

## Run Manual Scenarios

Send one command at a time, wait for it to finish, inspect the result, and only
then continue. `manual` means there is human-style review between scenarios; do
not send an entire acceptance suite as one script or replace inspection with
snapshot assertions.

Send command text literally so tmux does not interpret command characters as
key names:

```bash
tmux send-keys -t <pane-id> -l '<command>'
tmux send-keys -t <pane-id> Enter
```

Send control keys separately from literal command text:

```bash
tmux send-keys -t <pane-id> C-l
```

Check whether the pane has returned to its shell before inspecting it:

```bash
tmux display-message -p -t <pane-id> '#{pane_dead} #{pane_current_command} #{pane_in_mode}'
```

Do not rely only on a fixed sleep for long-running commands. Poll deliberately,
use the program's completion signal, or inspect the pane for its prompt.

## Inspect Rendering

Capture plain terminal layout for readability:

```bash
tmux capture-pane -p -t <pane-id> -S -100
```

Capture escape sequences when validating color or styling:

```bash
tmux capture-pane -p -e -t <pane-id> -S -100
```

Inspect output for hierarchy, wrapping, truncation, stale screen content,
prompts, progress cleanup, error visibility, and whether the command returned
control to the shell. ANSI presence alone does not prove that the layout is
usable.

## Width And Output Modes

Resize only the dedicated test window. Exercise at least narrow, normal, and
wide widths when layout is part of the task:

```bash
tmux resize-window -t <window-id> -x 60 -y 35
tmux resize-window -t <window-id> -x 100 -y 45
tmux resize-window -t <window-id> -x 140 -y 45
```

Choose scenarios relevant to the command, commonly:

- normal and verbose output;
- empty, error, and long-content states;
- text, structured, and tool-like content;
- multiple results or concurrent processes;
- redirected non-TTY output and machine-readable output;
- progress, cancellation, and return to the shell.

Keep deterministic automated assertions in the normal test suite. Use tmux to
judge terminal behavior that those tests cannot establish.

## Cleanup

Cleanup is mandatory even after a failed command or interrupted test.

If a window was created in a pre-existing session:

```bash
tmux kill-window -t <created-window-id>
```

If a dedicated session was created by the test:

```bash
tmux kill-session -t <created-session-id>
```

List resources again and verify that every created ID is gone and every
pre-existing resource remains:

```bash
tmux list-sessions -F '#{session_id} #{session_name}'
tmux list-windows -a -F '#{session_id} #{window_id} #{window_name}'
```

## Report

Report:

- the scenarios and terminal dimensions tested;
- the important visual and interactive observations;
- any failures or limitations;
- automated checks run separately from tmux;
- the IDs or names of created resources and confirmation that they were closed.
