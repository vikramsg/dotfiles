# Plan

## Goal

Document the correct Ghostty 1.3 AppleScript workflow for opening multiple tabs, connecting each tab to `ssh vm`, and naming each tab after the tmux session it attaches to.

## Scope

- add a dedicated Ghostty AppleScript document at `ghostty/script.md`
- add a pointer from `ghostty/README.md` to that new document
- keep all changes limited to documentation only

## Deliverables

1. `ghostty/script.md`
   - explains Ghostty's AppleScript object model
   - explains `new surface configuration`, `new window`, and `new tab`
   - explains why tab naming is done through terminal title escape sequences
   - includes a working multi-tab `osascript` example for remote tmux sessions
   - includes upstream references

2. `ghostty/README.md`
   - replaces the outdated keystroke-driven approach with a reference to `ghostty/script.md`

3. `plan.md`
   - records the documentation plan, acceptance criteria, and verification criteria

## Acceptance Criteria

- `ghostty/script.md` exists and describes the native Ghostty AppleScript approach rather than simulated keyboard automation
- `ghostty/script.md` includes a concrete example that opens multiple Ghostty tabs and runs `ssh vm -t tmux new-session -A -s <session>`
- `ghostty/script.md` explains how tab names are set to tmux session names
- `ghostty/script.md` includes source references for the documented behavior
- `ghostty/README.md` contains a clear reference to `ghostty/script.md`
- no files other than `ghostty/script.md`, `ghostty/README.md`, and `plan.md` are modified

## Verification Criteria

- confirm `ghostty/README.md` links readers to `ghostty/script.md`
- confirm `ghostty/script.md` mentions Ghostty AppleScript support, the object model, and `new surface configuration`
- confirm `ghostty/script.md` includes a runnable `osascript` example
- confirm `ghostty/script.md` includes verification steps for tab creation, session attach behavior, and tab naming
- confirm `plan.md` captures goal, scope, deliverables, acceptance criteria, and verification criteria

## Notes

- the previous README guidance used simulated `System Events` keystrokes; the new docs should steer readers to Ghostty's native AppleScript API instead
- the tab title is not set through a writable AppleScript tab property; it is driven by the terminal title emitted by the launched command
