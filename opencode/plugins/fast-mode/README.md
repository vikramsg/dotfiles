# fast-mode plugin

This plugin applies OpenAI `serviceTier` based on a global state file.

## Enable in config

Add this plugin entry to your OpenCode config:

```json
{
  "plugin": [
    "file:///home/vikram_orbio_earth/personal/dotfiles/opencode/plugins/fast-mode/index.ts"
  ]
}
```

## What it does

- Reads `~/.local/share/opencode/plugins/fast-mode.json` (or `$XDG_DATA_HOME/opencode/plugins/fast-mode.json` when `XDG_DATA_HOME` is set).
- In `chat.params`, sets OpenAI `serviceTier` to:
  - `priority` when `enabled=true`
  - `auto` when `enabled=false`
- Does nothing for non-OpenAI providers.

## State file

Path:

- Default: `~/.local/share/opencode/plugins/fast-mode.json`
- XDG override: `$XDG_DATA_HOME/opencode/plugins/fast-mode.json`

Format:

```json
{
  "enabled": true
}
```

Manage this file with `oc-fast`:

- `opencode/plugins/fast-mode/oc-fast on`
- `opencode/plugins/fast-mode/oc-fast off`
- `opencode/plugins/fast-mode/oc-fast status`
- `opencode/plugins/fast-mode/oc-fast toggle`

## Audit logging (opt-in)

Audit logging is disabled by default.

Set env var to enable:

```bash
export OPENCODE_FAST_MODE_AUDIT=1
```

Accepted truthy values: `1`, `true`, `yes`.

Audit path:

- Default: `~/.local/share/opencode/plugins/fast-mode.audit.log`
- XDG override: `$XDG_DATA_HOME/opencode/plugins/fast-mode.audit.log`

## Error behavior

- The plugin never throws from `chat.params`.
- On read/write failures it logs explicit errors to stderr with prefix `[fast-mode-plugin]`.
- If the state file cannot be read, fast mode defaults to OFF.

## TUI deterministic usage

From OpenCode TUI:

1. Press `!` at start of prompt to enter shell mode.
2. Run `opencode/plugins/fast-mode/oc-fast status` (or `on` / `off`).
