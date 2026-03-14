# Ghostty AppleScript Notes

This document explains how AppleScript works with Ghostty on macOS and how to open tabs that attach to remote tmux sessions.

## What Ghostty Exposes

Ghostty 1.3+ exposes a native AppleScript dictionary on macOS. The object model is:

`application -> windows -> tabs -> terminals`

The parts that matter for workspace automation are:

- `new surface configuration` creates a reusable launch record.
- `new window` and `new tab` create terminal surfaces from that record.
- `perform action` runs Ghostty action strings on a target terminal.
- `focused terminal` on `tab` provides the terminal target for `perform action`.
- `name` on `tab` is read-only in the AppleScript dictionary.

## Native Tab Renaming In 1.3.1

Ghostty 1.3.1 adds direct title actions, including `set_tab_title:<title>`. Use this natively from AppleScript through:

```applescript
perform action "set_tab_title:<title>" on <terminal>
```

Do not rely on terminal title escape sequences (`\033]0;...\007`) in this repo. Tab naming should use native Ghostty actions only.

## Recommended Pattern

Use one surface configuration per tab to launch the command you want, then immediately set the tab title with `set_tab_title`.

## Example: Open One Tab Per tmux Session

```bash
osascript <<'EOF'
set sessions to {"frontend", "backend", "db"}
set vmHost to "vm"

tell application "Ghostty"
    activate

    set win to new window

    repeat with sessionName in sessions
        set cfg to new surface configuration
        set command of cfg to "ssh " & vmHost & " -t tmux new-session -A -s " & sessionName

        set newTab to new tab in win with configuration cfg
        perform action ("set_tab_title:" & sessionName) on focused terminal of newTab
    end repeat
end tell
EOF
```

## How the Example Works

- `new surface configuration` creates per-tab launch configuration.
- `command of cfg` launches `ssh -t ... tmux new-session -A -s <name>`.
- `new tab in win with configuration cfg` returns the created tab.
- `perform action ("set_tab_title:" & sessionName) on focused terminal of newTab` applies the native tab title override.

## Notes

- AppleScript automation must be enabled (`macos-applescript = true`, enabled by default on macOS).
- The first time a script controls Ghostty, macOS may prompt for Automation permission.
- Use the installed dictionary (or upstream `Ghostty.sdef`) as source of truth for supported commands/properties.

## Running

- `osascript -e 'tell application "Ghostty" to get version'` prints Ghostty's app version.
- `osascript /path/to/script` runs the script.
- The example opens one tab per tmux session and names tabs via `set_tab_title`.

## Sources

1. Ghostty AppleScript docs: <https://ghostty.org/docs/features/applescript>
2. Ghostty features overview: <https://ghostty.org/docs/features>
3. Ghostty config reference (`macos-applescript`): <https://ghostty.org/docs/config/reference#macos-applescript>
4. Ghostty scripting dictionary (`perform action`, `focused terminal`, read-only `tab.name`): <https://github.com/ghostty-org/ghostty/blob/main/macos/Ghostty.sdef>
5. Ghostty PR adding `set_tab_title` and `set_surface_title`: <https://github.com/ghostty-org/ghostty/pull/11373>
6. Ghostty issue tracking title action support for AppleScript: <https://github.com/ghostty-org/ghostty/issues/11316>
