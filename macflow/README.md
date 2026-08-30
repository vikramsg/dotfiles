# macflow configuration

This directory contains the repo-managed configuration for the `macflow` tool.

## Source of truth

```text
repo: macflow/config.json
live: ${XDG_CONFIG_HOME:-~/.config}/macflow/config.json
```

Run `just macflow` to link the configuration and delegate build and installation
to `bin/macflow/justfile`.

The screenshot directory itself continues to come from the existing
`${XDG_CONFIG_HOME:-~/.config}/screenshot/config.json` file.

The screenshot shelf shows the newest `max_items` supported images. The value
defaults to five when omitted. Its fixed `width`, `height`, `thumbnail_width`,
`spacing`, and `margin` values control the shelf's compact layout.

Every hotkey requires an explicit `scope`. The supported `global` scope reserves
that chord for Macflow across all applications and consumes the event before
macOS or the focused application receives it. Removing the binding and
restarting Macflow restores normal handling.
