## Goal

Update this repo to use Ghostty 1.3.1's native tab-renaming path, replacing the old terminal-title escape workaround in both docs and the `ghostty-workspace` implementation. The correct integration point is `perform action "set_tab_title:..."` on a terminal, because Ghostty 1.3.1 adds `set_tab_title` as an action, `perform action` targets terminals, and `tab.name` is still read-only in the AppleScript dictionary. (`/tmp/ghostty-research/macos/Ghostty.sdef:67`, `/tmp/ghostty-research/macos/Ghostty.sdef:72`, `/tmp/ghostty-research/macos/Ghostty.sdef:154`, `/tmp/ghostty-research/src/input/Binding.zig:585`, `/tmp/ghostty-research/src/apprt/action.zig:204`, `/tmp/ghostty-research/src/Surface.zig:5495`, `https://github.com/ghostty-org/ghostty/pull/11373`, `https://github.com/ghostty-org/ghostty/issues/11316`)

**Guidance**
`Do Not` stop until all verification and acceptance criteria is met.
Start with a test first approach with writing failing tests, making sure they fail
and then proceeding with implementation.

## Architecture Diagram

```text
Current repo flow
-----------------
TOML workspace
   |
   v
render_applescript()
   |
   v
surface config command =
bash -lc '
  strip GHOSTTY_SHELL_FEATURES title bits
  export DISABLE_AUTO_TITLE=true
  printf "\033]0;TAB_NAME\007"
  run tab command
  exec "$SHELL" -l
'
   |
   v
Ghostty window/tab opens
   |
   v
shell escape sequence sets terminal/tab title indirectly

Sources:
- `bin/ghostty_workspace/ghostty_workspace/cli.py:33`
- `bin/ghostty_workspace/ghostty_workspace/templates/workspace.applescript.j2:1`
- `ghostty/script.md:43`
```

```text
Target flow
-----------
TOML workspace
   |
   v
render_applescript()
   |
   +--> create window/tab with normal command
   |
   +--> capture created tab or its focused terminal
   |
   v
perform action "set_tab_title:<name>" on <terminal>
   |
   v
Ghostty native tab title override applies
   |
   v
user command / ssh / tmux continues normally

Sources:
- `/tmp/ghostty-research/macos/Ghostty.sdef:72`
- `/tmp/ghostty-research/macos/Ghostty.sdef:154`
- `/tmp/ghostty-research/src/input/Binding.zig:585`
- `/tmp/ghostty-research/src/apprt/action.zig:204`
- `https://github.com/ghostty-org/ghostty/pull/11373`
```

## Current Status

- Upstream Ghostty 1.3.1 supports native title actions through `perform action`, and specifically adds `set_tab_title` for AppleScript-driven renaming. (`/tmp/ghostty-research/macos/Ghostty.sdef:154`, `/tmp/ghostty-research/src/input/Binding.zig:585`, `https://github.com/ghostty-org/ghostty/pull/11373`)
- The repo docs still describe tab renaming as an indirect OSC escape-sequence hack and teach `printf '\033]0;...` before `ssh`. (`ghostty/script.md:43`, `ghostty/script.md:83`)
- The `ghostty-workspace` code still strips title-related shell features, exports `DISABLE_AUTO_TITLE=true`, and emits the OSC title sequence in `_build_tab_shell_command()`. (`bin/ghostty_workspace/ghostty_workspace/cli.py:33`)
- The AppleScript template already uses `perform action` for focus via `goto_tab:N`, so the codebase already has the right mechanism available; it just is not using it yet for naming. (`bin/ghostty_workspace/ghostty_workspace/templates/workspace.applescript.j2:16`, `bin/ghostty_workspace/tests/test_ghostty_workspace_cli.py:62`)
- The top-level Ghostty docs in this repo also point readers at the old "set each tab title before `ssh`" behavior, so there is a doc sync task beyond code. (`ghostty/README.md:47`)

## Short summary of changes

- Change `ghostty/script.md` to document Ghostty 1.3.1's native tab-renaming flow: `new tab` / `new window`, then `perform action "set_tab_title:..."` on the tab's focused terminal, while noting that `tab.name` remains read-only. (`ghostty/script.md:43`, `/tmp/ghostty-research/macos/Ghostty.sdef:67`, `/tmp/ghostty-research/macos/Ghostty.sdef:154`)
- Refactor `bin/ghostty_workspace/ghostty_workspace/cli.py` so `_build_tab_shell_command()` only handles path setup, optional tab command, and login-shell handoff; remove title escape logic and title-disabling env mutations. (`bin/ghostty_workspace/ghostty_workspace/cli.py:33`)
- Extend `bin/ghostty_workspace/ghostty_workspace/templates/workspace.applescript.j2` to issue `perform action "set_tab_title:..."` after each window/tab is created, using the created tab's focused terminal or the selected tab in the new window. (`bin/ghostty_workspace/ghostty_workspace/templates/workspace.applescript.j2:1`, `/tmp/ghostty-research/macos/Ghostty.sdef:72`, `/tmp/ghostty-research/macos/Ghostty.sdef:154`)
- Update tests so they fail on the current implementation and then pass only when native renaming is used, including assertions that the old OSC path is gone. (`bin/ghostty_workspace/tests/test_ghostty_workspace_cli.py:48`, `bin/ghostty_workspace/tests/test_ghostty_workspace_cli.py:114`)
- Refresh `ghostty/README.md` and likely `bin/ghostty_workspace/README.md` so the docs match the new native behavior. (`ghostty/README.md:47`, `bin/ghostty_workspace/README.md:49`)

### Options considered

- Recommended: use `perform action "set_tab_title:..."` on a terminal after tab creation; this matches the new 1.3.1 action model and avoids shell-title hacks. (`/tmp/ghostty-research/macos/Ghostty.sdef:154`, `/tmp/ghostty-research/src/input/Binding.zig:585`, `https://github.com/ghostty-org/ghostty/pull/11373`)
- Do not use `set name of tab ...`; Ghostty's AppleScript dictionary still marks `tab.name` as read-only. (`/tmp/ghostty-research/macos/Ghostty.sdef:64`)
- Do not keep the OSC escape workaround as the primary path; it is now stale in docs and adds unnecessary shell/env manipulation in the CLI. (`ghostty/script.md:47`, `bin/ghostty_workspace/ghostty_workspace/cli.py:35`)
- Enforce a hard cutover with no fallback and no legacy mode in this repo: only native `perform action "set_tab_title:..."` is supported. (`https://github.com/ghostty-org/ghostty/pull/11373`, `/tmp/ghostty-research/macos/Ghostty.sdef:154`)

## Files to be changed

- `ghostty/script.md`
  - Replace the "Why Tab Renaming Works Indirectly" section with native 1.3.1 guidance.
  - Update the example to remove `titleSeq` and call `perform action ("set_tab_title:" & sessionName)`.
  - Update explanatory bullets and sources to mention `perform action`, `focused terminal`, and `set_tab_title`. (`ghostty/script.md:43`, `/tmp/ghostty-research/macos/Ghostty.sdef:72`, `/tmp/ghostty-research/macos/Ghostty.sdef:154`, `https://github.com/ghostty-org/ghostty/pull/11373`)
- `ghostty/README.md`
  - Change the summary bullet from "set each tab title before `ssh`" to native AppleScript naming in 1.3.1. (`ghostty/README.md:47`)
- `bin/ghostty_workspace/ghostty_workspace/cli.py`
  - Remove title-specific shell feature stripping and OSC `printf`.
  - Pass an AppleScript-escaped tab title into the template alongside the shell command.
  - Keep the login shell behavior and path resolution intact. (`bin/ghostty_workspace/ghostty_workspace/cli.py:29`, `bin/ghostty_workspace/ghostty_workspace/cli.py:33`)
- `bin/ghostty_workspace/ghostty_workspace/templates/workspace.applescript.j2`
  - Capture the created tab/window state and add `perform action "set_tab_title:..."`.
  - Preserve the existing startup delay and `goto_tab:N` focus behavior unless tests show a better native selection path. (`bin/ghostty_workspace/ghostty_workspace/templates/workspace.applescript.j2:7`, `bin/ghostty_workspace/ghostty_workspace/templates/workspace.applescript.j2:14`)
- `bin/ghostty_workspace/tests/test_ghostty_workspace_cli.py`
  - Rewrite existing title-related assertions to target native rename actions.
  - Add negative assertions proving the old title escape path is gone.
  - Add escaping-focused coverage for tab names with quotes/backslashes. (`bin/ghostty_workspace/tests/test_ghostty_workspace_cli.py:48`, `bin/ghostty_workspace/tests/test_ghostty_workspace_cli.py:114`)
- `bin/ghostty_workspace/README.md`
  - Clarify that `tabs[].name` is applied via Ghostty native AppleScript action, not shell title escapes. (`bin/ghostty_workspace/README.md:49`, `bin/ghostty_workspace/README.md:83`)

## Files to be added

- None expected; the current implementation and test structure should support this change in-place. (`bin/ghostty_workspace/tests/test_ghostty_workspace_cli.py:48`, `bin/ghostty_workspace/ghostty_workspace/templates/workspace.applescript.j2:1`)

## Verification Criteria

- Unit tests in `bin/ghostty_workspace/tests/test_ghostty_workspace_cli.py` first fail on the current code when they assert for `set_tab_title` usage and absence of the OSC workaround, then pass after implementation. (`bin/ghostty_workspace/tests/test_ghostty_workspace_cli.py:48`, `bin/ghostty_workspace/tests/test_ghostty_workspace_cli.py:114`)
- Rendered AppleScript includes both:
  - `perform action "goto_tab:N"` for focus, and
  - `perform action "set_tab_title:..."` for naming. (`bin/ghostty_workspace/ghostty_workspace/templates/workspace.applescript.j2:18`, `/tmp/ghostty-research/macos/Ghostty.sdef:154`)
- Rendered shell commands no longer include:
  - `DISABLE_AUTO_TITLE=true`
  - `GHOSTTY_SHELL_FEATURES` title stripping
  - `printf '\033]0;...` title emission. (`bin/ghostty_workspace/ghostty_workspace/cli.py:35`)
- Docs no longer claim tab renaming only works indirectly or "before `ssh`"; they explicitly describe Ghostty 1.3.1 native title actions. (`ghostty/script.md:43`, `ghostty/README.md:52`)
- Manual macOS smoke check on Ghostty 1.3.1 confirms tabs open with the requested names and still focus the configured tab correctly when using `ghostty-workspace`. (`bin/ghostty_workspace/README.md:83`, `https://ghostty.org/docs/features/applescript`)

## Acceptance Criteria

- The repo's documented recommendation for Ghostty tab naming matches upstream 1.3.1 behavior and cites the new native mechanism. (`ghostty/script.md:19`, `/tmp/ghostty-research/macos/Ghostty.sdef:154`, `https://github.com/ghostty-org/ghostty/pull/11373`)
- `ghostty-workspace` no longer relies on OSC title escapes for tab naming. (`bin/ghostty_workspace/ghostty_workspace/cli.py:47`)
- The tab title is applied by AppleScript using `perform action "set_tab_title:..."` on a terminal. (`/tmp/ghostty-research/macos/Ghostty.sdef:154`, `/tmp/ghostty-research/src/input/Binding.zig:585`)
- Existing focus behavior remains intact and covered by tests. (`bin/ghostty_workspace/ghostty_workspace/templates/workspace.applescript.j2:18`, `bin/ghostty_workspace/tests/test_ghostty_workspace_cli.py:62`)
- User-facing docs in both `ghostty/` and `bin/ghostty_workspace/` are internally consistent. (`ghostty/README.md:47`, `bin/ghostty_workspace/README.md:49`)

## Checklist of tasks to be done

1. Add failing tests in `bin/ghostty_workspace/tests/test_ghostty_workspace_cli.py` that assert the rendered AppleScript contains `set_tab_title`, and that generated shell commands no longer include `DISABLE_AUTO_TITLE`, `GHOSTTY_SHELL_FEATURES` title stripping, or `printf '\033]0;...`. Base them on the current render and command helpers. (`bin/ghostty_workspace/tests/test_ghostty_workspace_cli.py:48`, `bin/ghostty_workspace/tests/test_ghostty_workspace_cli.py:114`, `bin/ghostty_workspace/ghostty_workspace/cli.py:33`)
2. Run `uv run pytest` from `bin/ghostty_workspace` to prove those tests fail on the current implementation; if they do not fail, strengthen the assertions until they specifically distinguish the old workaround from the new native path. (`bin/ghostty_workspace/README.md:87`)
3. Implement the code change in `bin/ghostty_workspace/ghostty_workspace/cli.py` so shell command generation stops managing titles and instead provides clean, escaped title data to the template. (`bin/ghostty_workspace/ghostty_workspace/cli.py:29`, `bin/ghostty_workspace/ghostty_workspace/cli.py:33`)
4. Update `bin/ghostty_workspace/ghostty_workspace/templates/workspace.applescript.j2` to issue `perform action "set_tab_title:..."` after each tab/window is created, using `focused terminal` as the action target and preserving the existing startup-order delay and `goto_tab:N` focus step. (`bin/ghostty_workspace/ghostty_workspace/templates/workspace.applescript.j2:1`, `/tmp/ghostty-research/macos/Ghostty.sdef:72`, `/tmp/ghostty-research/macos/Ghostty.sdef:154`)
5. Add or extend tests for title escaping so tab names with quotes and backslashes render valid AppleScript action strings. (`bin/ghostty_workspace/ghostty_workspace/cli.py:29`, `bin/ghostty_workspace/tests/test_ghostty_workspace_cli.py:48`)
6. Re-run `uv run pytest` from `bin/ghostty_workspace` and confirm the full package test suite passes, including focus-tab coverage that already guards `goto_tab:N` behavior. (`bin/ghostty_workspace/tests/test_ghostty_workspace_cli.py:62`, `bin/ghostty_workspace/tests/test_ghostty_workspace_cli.py:128`)
7. Update `ghostty/script.md` to replace the indirect-renaming explanation, rewrite the example script, and add source references for `perform action`, `focused terminal`, and `set_tab_title`. (`ghostty/script.md:43`, `/tmp/ghostty-research/macos/Ghostty.sdef:72`, `/tmp/ghostty-research/macos/Ghostty.sdef:154`, `https://github.com/ghostty-org/ghostty/pull/11373`)
8. Update `ghostty/README.md` and `bin/ghostty_workspace/README.md` so they describe native tab renaming consistently and no longer imply the title must be set before `ssh`. (`ghostty/README.md:47`, `bin/ghostty_workspace/README.md:49`)
9. Perform a local macOS smoke check with Ghostty 1.3.1 by running `ghostty-workspace --config ghostty/workspaces/example.toml` and a minimal `osascript` example from the docs, verifying that tab titles match the requested names and focus lands on `focus_tab`; no browser skill is available here, so this manual app smoke check is the right substitute. (`ghostty/workspaces/example.toml`, `bin/ghostty_workspace/README.md:65`, `https://ghostty.org/docs/features/applescript`)
10. Do a final doc/code consistency pass to ensure every mention of tab naming, AppleScript behavior, and verification steps aligns with the implemented 1.3.1-native approach. (`ghostty/script.md:1`, `ghostty/README.md:43`, `bin/ghostty_workspace/README.md:69`)
