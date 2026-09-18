# macflow configuration

This directory contains the repo-managed configuration for the `macflow` tool.

## Source of truth

```text
repo: macflow/config.json
live: ${XDG_CONFIG_HOME:-~/.config}/macflow/config.json
```

Run `just macflow` to link the configuration and delegate build and installation
to `bin/macflow/justfile`. Run it from the checkout that should own your live
configuration, not a temporary worktree. On macOS it also links the Macflow skill
to `~/.config/opencode/skills/macflow`.

For first-time setup, follow [BOOTSTRAP.md](BOOTSTRAP.md). For command usage, see
the [action](../bin/macflow/docs/actions.md) and [UI](../bin/macflow/docs/ui.md) guides.

## What to configure

| Section | Responsibility |
| --- | --- |
| `server` | Local HTTP host and port used by the app and CLI |
| `applications` | Application aliases and their bundle IDs |
| `layouts` | Maximize/column participants, ratios, target screen, gap, and focus |
| `hotkeys` | Global shortcuts that invoke configured layouts |
| `screenshots` | Capture directory, supported images, debounce, and preview behavior |
| `appearance` | Built-in theme selection |

The format is JSON; see [config.json](config.json) for the complete working
example. Layout and hotkey changes require restarting the app.

## UI surfaces

UI is described by a JSON payload sent with `macflow ui show` or `POST /v1/ui`,
not by configuration. Themes and panel geometry travel with the payload. See the
[UI workflows guide](../bin/macflow/docs/ui.md).

## Configured layouts

The checked-in shortcuts are:

| Shortcut | Action |
| --- | --- |
| Cmd+Shift+1 | Maximize Ghostty |
| Cmd+Shift+2 | Maximize Zed |
| Cmd+Shift+3 | Ghostty left, Zed right; focus Ghostty |
| Cmd+Shift+4 | Zed left, Ghostty right; focus Zed |

These reserve macOS's usual Cmd+Shift+3/4 screenshot chords. Cmd+Shift+5 still
opens the native screenshot controls. Your bindings may differ; consult the
active JSON before sending a shortcut.

Every hotkey requires an explicit `scope`. The supported `global` scope reserves
that chord for Macflow across all applications and consumes the event before
macOS or the focused application receives it. Removing the binding and
restarting Macflow restores normal handling.

`appearance.theme` selects a theme built into Macflow. `system` and
`tokyo-night` are supported. Theme definitions are application resources, not
user configuration.

Macflow owns its configured directories directly. The root `justfile` checks
that Macflow's screenshot directory matches the independently owned
`screenshot/config.json` path before either tool is installed.
