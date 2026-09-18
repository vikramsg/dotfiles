---
name: macflow
description: Use Macflow on macOS to inspect and arrange windows, capture screenshots, send keyboard or mouse input, present image overlays, render JSON-described native UI, list files, and diagnose its service and permissions. Use for Macflow CLI workflows and configuration.
---

# Macflow

Macflow's CLI is an HTTP client for its signed macOS app. All desktop state and
actions belong to that app. Never replace a failing Macflow command with a
direct AppKit, Accessibility, AppleScript, or other macOS automation fallback.

## Discover and check

1. Confirm `uname` is `Darwin`. Otherwise stop: Macflow runs only on macOS.
2. Run `macflow --help` and the relevant group's `--help`. The installed CLI is
   the authority; do not guess arguments or assume a roadmap feature exists.
3. Run `macflow system health` and `macflow system doctor` before desktop actions.
   If the service is unavailable, inspect `lch status lch-macflow` and report the
   failure. Do not reinstall or restart services without authorization.
4. Missing permissions belong to `~/Applications/Macflow.app`, not the terminal.
   Explain the missing access; use `macflow system permissions request --help`
   when the user wants to grant it. Never revoke working permissions to test a
   failure. If Secure Input is enabled, ask the user to close password prompts;
   do not terminate their apps or login session.

## Choose the right responsibility

Command paths below are shorthand: prefix them with `macflow`.
For example, `app list` means `macflow app list`.

```text
app          list or launch applications
window       inspect, position, focus, or unminimize windows
screen       inspect display geometry
input        send keystrokes, clicks, or drags
screenshot   capture a display
files        list files for building a UI
ui           create, inspect, or dismiss JSON-described UI surfaces
overlay      show, inspect, or hide image overlays
system       health, doctor, permissions
```

Capture and window actions do not require Macflow UI. Use UI only when the user
wants a visible surface. `screenshot capture --preview` is an explicit opt-in.

## Inspect → act → verify

- **Windows:** use `app list`, `window list <bundle-id>`, and `screen list` first.
  Use freshly returned IDs and geometry. Launch/focus may change the active app;
  frame changes move or resize windows. Re-list to confirm the outcome. Do not
  move unrelated windows. Restore temporary verification changes afterward.
- **Capture:** use `screenshot capture --path <file.png>` for an explicit
  destination. It hides the transient overlay and does not show a new preview
  by default. Verify the returned path, dimensions, and image as appropriate.
  Screenshots can contain private information; do not upload or share them
  unless requested. The configured default directory may participate in sync.
- **Input:** inspect the target before `input keystroke`, `input click`, or
  `input drag`. Recheck the active application before typing; stop if focus
  changes or the user is working in the same desktop. A success response
  acknowledges input dispatch; it does not prove
  the target reacted or a drag finished. Verify the visible or file outcome.
- **Overlay:** `overlay show <image-path> [timeout-seconds]`, then
  `overlay list`; `overlay hide` dismisses it without capturing anything.
- **UI:** build an A2UI payload and `ui show --file <payload.json>` (or `-` for
  stdin); `ui list` reports surfaces. Render it, then verify visually with
  `screenshot capture` and dismiss with `ui dismiss <surface-id>` or Escape.
  Payloads are one message or an array; see `docs/ui.md`.
- **Files:** `files list <directory>` returns newest-first `name`, `path`, `url`,
  and `modifiedAt`. Use it to fill a surface's data model.
- **Configured workflows:** inspect the user's config before sending a hotkey.
  Layouts can be bound there. Do not assume a shortcut or invent `layout apply`.
  Confirm dismissal and focus restoration visually when relevant.

## Configuration and installation

Configuration is `${XDG_CONFIG_HOME:-~/.config}/macflow/config.json`. 
