# Ghostty AppleScript Notes

This document explains how AppleScript works with Ghostty on macOS and how to use it to open multiple tabs that attach to remote tmux sessions.

## What Ghostty Exposes

Ghostty 1.3 introduces a native AppleScript dictionary on macOS. The object model is:

`application -> windows -> tabs -> terminals`

The pieces that matter for tab automation are:

- `new surface configuration` creates a reusable record for a terminal launch.
- `new window` opens a new window, optionally with a surface configuration.
- `new tab` opens a new tab in a target window, optionally with a surface configuration.
- `input text` and `send key` can drive an already-open terminal.
- `name` exists on tabs and terminals, but it reflects the current terminal title instead of being a writable AppleScript property.

References:

- Ghostty AppleScript docs: <https://ghostty.org/docs/features/applescript>
- Ghostty scripting definition: <https://github.com/ghostty-org/ghostty/blob/main/macos/Ghostty.sdef>

## Why Tab Renaming Works Indirectly

Ghostty exposes the tab `name`, but the AppleScript dictionary defines it as a read-only property. 
In practice, Ghostty updates that title from the terminal process. 
That means the reliable way to rename a tab is to emit a terminal title escape sequence from the command that launches inside the tab.

The standard sequence used here is:

```text
\033]0;TAB_NAME\007
```

That lets the tab title become the tmux session name before the `ssh` process takes over.

References:

- Ghostty `tab` properties in `Ghostty.sdef`: <https://github.com/ghostty-org/ghostty/blob/main/macos/Ghostty.sdef>
- Ghostty AppleScript implementation: <https://github.com/ghostty-org/ghostty/blob/main/macos/Sources/Features/AppleScript/AppDelegate+AppleScript.swift>

## Recommended Pattern

Use a surface configuration per tab and set its `command` to a small shell wrapper that:

1. prints the title escape sequence
2. `exec`s into `ssh`
3. runs `tmux new-session -A -s <session>` on the remote host

Using `exec` matters because Ghostty then treats `ssh` as the primary process for that tab.

## Example: Open One Tab Per tmux Session

```bash
osascript <<'EOF'
set sessions to {"frontend", "backend", "db"}
set vmHost to "vm"

tell application "Ghostty"
    activate

    repeat with sessionName in sessions
        set titleSeq to "\\033]0;" & sessionName & "\\007"
        set cmd to "bash -c 'printf \"" & titleSeq & "\"; exec ssh " & vmHost & " -t tmux new-session -A -s " & sessionName & "'"

        set cfg to new surface configuration
        set command of cfg to cmd

        new tab in front window with configuration cfg
    end repeat
end tell
EOF
```

## How the Example Works

- `activate` brings Ghostty to the foreground.
- `new surface configuration` creates a per-tab launch config.
- `command of cfg` overrides the normal shell for that new tab.
- `printf` emits the title sequence so the tab title becomes the session name.
- `ssh -t` forces pseudo-terminal allocation, which tmux needs.
- `tmux new-session -A -s <name>` attaches to the session if it exists or creates it if it does not.

## Notes and Constraints

- AppleScript automation must be enabled. The Ghostty config key is `macos-applescript = true` and it is enabled by default on macOS.
- The first time a script controls Ghostty, macOS may prompt for Automation permission.
- The example assumes a Ghostty window already exists because it opens tabs in `front window`. If needed, create a window first with `new window` and then add tabs to that returned window.
- If you want a scriptable source of truth for supported AppleScript objects and commands, use the installed app dictionary or the upstream `Ghostty.sdef` file.

References:

- AppleScript security and config flag: <https://ghostty.org/docs/features/applescript>
- Config reference for `macos-applescript`: <https://ghostty.org/docs/config/reference#macos-applescript>

## Alternative: Explicit New Window First

If you do not want to depend on an already-open Ghostty window, use this pattern first:

```applescript
tell application "Ghostty"
    set win to new window
    new tab in win
end tell
```

Then target `win` instead of `front window` in the multi-tab script.

## Verification Checklist

- Running `osascript -e 'tell application "Ghostty" to get version'` returns a Ghostty version.
- Running the example opens one tab per session.

## Sources

1. Ghostty AppleScript docs: <https://ghostty.org/docs/features/applescript>
2. Ghostty features overview: <https://ghostty.org/docs/features>
3. Ghostty config reference: <https://ghostty.org/docs/config/reference#macos-applescript>
4. Ghostty scripting dictionary: <https://github.com/ghostty-org/ghostty/blob/main/macos/Ghostty.sdef>
5. Ghostty AppleScript implementation: <https://github.com/ghostty-org/ghostty/blob/main/macos/Sources/Features/AppleScript/AppDelegate+AppleScript.swift>
