# macflow configuration

This directory contains the repo-managed configuration for the `macflow` tool.

## Source of truth

```text
repo: macflow/config.json
live: ${XDG_CONFIG_HOME:-~/.config}/macflow/config.json

repo: macflow/ui/
live: ${XDG_CONFIG_HOME:-~/.config}/macflow/ui/
```

Run `just macflow` to link the configuration and delegate build and installation
to `bin/macflow/justfile`.

## Web surfaces

`config.json` can register a local WebKit surface by document path, panel size,
placement margin, activation behavior, drag-close behavior, and an opaque
`configuration` object. Macflow passes that object to the page without
interpreting its domain fields.

The checked-in `screenshots-web` surface loads
`ui/screenshot-shelf/index.html`. Its HTML, CSS, and JavaScript define the
entire shelf UI; changing those files does not require recompiling Macflow.
Macflow provides only the native panel lifecycle, semantic theme variables,
and generic file operations.

Macflow owns its configured directories directly. The root `justfile` checks
that Macflow's screenshot paths match the independently owned
`screenshot/config.json` path before either tool is installed.

The screenshot shelf shows one tab per configured source. Each source has a
stable ID, label, SF Symbol name, and explicit directory. The two checked-in
sources currently use the local screenshot directory so the complete tabbed
workflow can be exercised without depending on a remote host. The remote source
must be changed and verified against a real remote VM before that integration is
considered complete.

Each tab shows the newest `max_items` supported images. The value defaults to
five when omitted. The fixed `width`, `height`, `thumbnail_width`, `spacing`,
and `margin` values control the shelf's compact layout. Visible shelves watch
their source directories and refresh when files change.

`appearance.theme` selects a theme built into Macflow. `system` and
`tokyo-night` are supported. Theme definitions are application resources, not
user configuration.

Every hotkey requires an explicit `scope`. The supported `global` scope reserves
that chord for Macflow across all applications and consumes the event before
macOS or the focused application receives it. Removing the binding and
restarting Macflow restores normal handling.

`cmd + shift + h` opens the native shelf. `cmd + shift + j` opens the WebKit
shelf so both implementations can be compared without replacing the existing
workflow.
