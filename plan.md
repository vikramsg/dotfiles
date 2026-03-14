## Goal

Implement a new screenshot-domain tool and a thin `launchd` orchestrator so that:

- `screenshot` is the single owner of screenshot-specific configuration and state.
- `lch` is the single owner of `launchd` job creation, installation, and dispatch.
- The first `lch` job is `lch-screenshot-clipboard`.
- Native macOS screenshot UX remains unchanged.
- The last 5 copied screenshot paths are stored as screenshot state and are accessible through the `screenshot` CLI.
- The work is executed end to end without stopping until implementation, verification, docs, and acceptance criteria are complete.

**Guidance**
`Do Not` stop until all verification and acceptance criteria is met.
Start with a test first approach with writing failing tests, making sure they fail
and then proceeding with implementation.

## Architecture Diagram

Overall event flow:

```text
+-------------------+       +-------------------+       +----------------------+
| macOS Screenshot  | ----> | screenshot_dir    | ----> | launchd WatchPaths   |
| UI / Shift-Cmd-4  |       | ~/Screenshots     |       | wakes lch job        |
+-------------------+       +-------------------+       +----------+-----------+
                                                                  |
                                                                  v
                                                     +---------------------------+
                                                     | lch run                   |
                                                     | lch-screenshot-clipboard  |
                                                     +-------------+-------------+
                                                                   |
                                                                   v
                                                     +---------------------------+
                                                     | screenshot clipboard      |
                                                     | on-event                  |
                                                     | - find latest screenshot  |
                                                     | - copy path to clipboard  |
                                                     | - update last 5 history   |
                                                     +-------------+-------------+
                                                                   |
                                                                   v
                                                     +---------------------------+
                                                     | ~/.local/state/screenshot |
                                                     | clipboard-history.json    |
                                                     +---------------------------+
```

Ownership boundaries:

```text
screenshot
  owns:
    - screenshot_dir
    - screenshot filename filters
    - sync config
    - clipboard_history_limit
    - clipboard history state
    - "which screenshot should be copied now?"

lch
  owns:
    - launchd labels
    - plist generation
    - install/uninstall/status/logs
    - dispatch to screenshot commands
```

Install and run flow:

```text
lch install lch-screenshot-clipboard
  -> ask screenshot for watch path
  -> generate plist with WatchPaths
  -> install LaunchAgent

launchd event
  -> lch run lch-screenshot-clipboard
  -> execute: screenshot clipboard on-event

screenshot clipboard on-event
  -> load config
  -> scan screenshot_dir
  -> find newest matching screenshot
  -> skip if already history head
  -> pbcopy absolute path
  -> prepend to history
  -> trim history to last 5
```

## Current Status

- The repo already has a packaged `uv` tool pattern under `bin/<tool>/` with local `pyproject.toml`, package-local tests, and root workspace membership.
- `screenshot_sync` already owns `screenshot_dir`, which suggests screenshot folder configuration belongs in the screenshot domain, not in `lch`.
- `screenshot_sync` currently also owns its own `launchd` integration, which is the coupling to remove in the new design.
- Root pytest discovery currently includes only the existing package-local test directories, so any new tool package must be added to the root workspace and root `testpaths`.
- `launchd` `WatchPaths` can wake a job when a directory changes, but it does not tell the launched process which file changed.
- Apple allows changing the screenshot save location, so the design should assume a dedicated folder like `~/Screenshots` instead of the desktop.

## Short summary of changes

- Add a new canonical `screenshot` tool as a `uv`-managed package under `bin/screenshot/`.
- Move screenshot-domain concerns into `screenshot`:
  - `sync` subcommands for rsync behavior
  - `clipboard` subcommands for event handling and history access
  - central config and state ownership
- Add a new `lch` tool as a `uv`-managed package under `bin/lch/`.
- Make `lch` responsible only for `launchd` job management and command dispatch.
- Start with a single `lch` job:
  - job id: `lch-screenshot-clipboard`
  - recommended label: `com.vikramsg.dotfiles.lch-screenshot-clipboard`
  - execution target: `screenshot clipboard on-event`
- Store the "last 5 copied screenshots" in screenshot state, not config.
- Add three architecture docs with diagrams:
  - one architecture doc in `bin/screenshot`
  - one architecture doc in `bin/lch`
  - one interaction doc in `bin/lch` explaining how `lch` interacts with `screenshot`

### Options considered

- **Recommended: single `screenshot` tool + thin `lch`**
  - one owner for `screenshot_dir`
  - one owner for clipboard history and sync config
  - no duplication of screenshot matching logic
  - `lch` stays generic and launchd-focused

- **Separate `screenshot_sync` and `screenshot_clipboard` tools**
  - rejected for the first implementation because it duplicates ownership questions around screenshot folder, matching rules, and shared config/state.

- **Make `lch` own screenshot folder config**
  - rejected because folder choice is screenshot-domain behavior, not launchd-domain behavior.

- **Keep clipboard history in config**
  - rejected because history is runtime state, not stable configuration.

- **Keep `lch` as a plain executable in `bin/`**
  - considered, but not recommended; `lch` will have enough logic and tests to justify the same `uv` package structure already used by other tools.

## Files to be changed

- `pyproject.toml`
  - add `bin/screenshot` and `bin/lch` to workspace members
  - add their test directories to root pytest `testpaths`
- `bin/README.md`
  - add install/test/docs sections for `screenshot` and `lch`

Optional later migration targets, but not required in the first implementation step:

- `bin/screenshot_sync/README.md`
- `bin/screenshot_sync/screenshot_sync/cli.py`

## Files to be added

Recommended new canonical screenshot tool:

- `bin/screenshot/pyproject.toml`
- `bin/screenshot/README.md`
- `bin/screenshot/docs/architecture.md`
- `bin/screenshot/screenshot/__init__.py`
- `bin/screenshot/screenshot/cli.py`
- `bin/screenshot/screenshot/config.py`
- `bin/screenshot/screenshot/clipboard.py`
- `bin/screenshot/screenshot/sync.py`
- `bin/screenshot/screenshot/state.py`
- `bin/screenshot/tests/test_screenshot_clipboard_cli.py`
- `bin/screenshot/tests/test_screenshot_clipboard_history.py`
- `bin/screenshot/tests/test_screenshot_sync_cli.py`
- `bin/screenshot/tests/test_screenshot_config.py`

Recommended `launchd` orchestrator:

- `bin/lch/pyproject.toml`
- `bin/lch/README.md`
- `bin/lch/docs/architecture.md`
- `bin/lch/docs/screenshot-integration.md`
- `bin/lch/lch/__init__.py`
- `bin/lch/lch/cli.py`
- `bin/lch/lch/jobs.py`
- `bin/lch/lch/launchd.py`
- `bin/lch/tests/test_lch_cli.py`
- `bin/lch/tests/test_lch_launchd.py`
- `bin/lch/tests/test_lch_job_dispatch.py`

Optional if data-driven jobs are needed immediately:

- `bin/lch/lch/jobs/lch-screenshot-clipboard.toml`

## Verification Criteria

- `screenshot` tests verify:
  - config loads `screenshot_dir`, clipboard history limit, and sync settings correctly
  - `clipboard on-event` finds the newest valid screenshot candidate
  - only screenshot filename patterns are eligible
  - the absolute path is copied to the clipboard
  - history is prepended and trimmed to the most recent 5 items
  - `clipboard list` shows the most recent 5 copied screenshot paths
  - `clipboard copy --index N` recopies a prior item from history
  - sync command construction preserves existing rsync behavior
- `lch` tests verify:
  - `lch-screenshot-clipboard` resolves to the expected label
  - the generated LaunchAgent plist uses the correct label/path conventions
  - `WatchPaths` points to the screenshot folder returned by `screenshot`
  - `ProgramArguments` run `lch run lch-screenshot-clipboard`
  - `lch run lch-screenshot-clipboard` dispatches to `screenshot clipboard on-event`
- Root repo verification proves:
  - `uv run pytest` from repo root includes the new test directories
  - `uv tool install ./bin/screenshot --force --no-cache` succeeds
  - `uv tool install ./bin/lch --force --no-cache` succeeds
  - `screenshot --help` and `lch --help` both succeed
- Final documentation verification proves:
  - `plan.md` exists at repo root
  - `bin/screenshot/docs/architecture.md` exists and contains diagrams
  - `bin/lch/docs/architecture.md` exists and contains diagrams
  - `bin/lch/docs/screenshot-integration.md` exists and explains the `lch` <-> `screenshot` interaction with diagrams
- Manual macOS verification proves:
  - Screenshot app save location is set to `~/Screenshots`
  - `lch install lch-screenshot-clipboard` installs the LaunchAgent
  - taking a native screenshot updates the clipboard with the newest screenshot path
  - after multiple screenshots, `screenshot clipboard list` shows the last 5 copied paths in order
  - `screenshot clipboard copy --index N` restores an older path to the clipboard

## Acceptance Criteria

- There is one screenshot-domain tool, `screenshot`, that owns:
  - screenshot folder configuration
  - screenshot matching rules
  - clipboard history limit
  - clipboard history state
  - sync configuration
- There is one launchd-domain tool, `lch`, that owns:
  - LaunchAgent label generation
  - plist generation
  - install/uninstall/status/logs
  - dispatch to the screenshot command
- The first job is `lch-screenshot-clipboard`.
- Clipboard history stores the last 5 copied screenshot paths in state, not config.
- `screenshot clipboard on-event` is safe to invoke repeatedly and does not grow history beyond the configured limit.
- The implementation is fully test-first:
  - failing tests written first
  - failures observed
  - implementation added after validated failures
- Native macOS screenshot behavior remains intact.
- Final docs exist with diagrams in all required locations.
- All package-local tests, root tests, install smoke checks, manual macOS checks, and doc checks pass.

## Checklist of tasks to be done

1. Write this full plan to `plan.md` before starting any implementation work.
2. Verify that `plan.md` exists at repo root and matches the agreed architecture, docs requirements, and end-to-end flow.

3. Write failing tests for the new `screenshot` config model:
   - `screenshot_dir`
   - `clipboard_history_limit`
   - sync settings
   - default values and env overrides if retained.
4. Run only the new `screenshot` config tests and confirm they fail for the expected missing-module or missing-behavior reasons; if not, fix the tests first.
5. Implement the minimum config loader needed to satisfy those failing config tests.
6. Re-run the config tests until they pass.

7. Write failing tests for `screenshot clipboard on-event`:
   - newest screenshot selection
   - allowed filename patterns
   - clipboard invocation
   - no non-screenshot matches.
8. Run those clipboard event tests and confirm they fail before implementing any clipboard logic.
9. Implement the minimum screenshot clipboard event flow needed to make those tests pass.
10. Re-run the clipboard event tests until they pass.

11. Write failing tests for clipboard history behavior:
   - prepend newest copied path
   - cap list length at 5
   - preserve newest-first ordering
   - support `clipboard list`
   - support `clipboard copy --index N`.
12. Run those history tests and validate they fail; if they pass unexpectedly, tighten the assertions.
13. Implement screenshot clipboard history state management.
14. Re-run history tests until they pass.

15. Write failing tests for the sync subcommands by porting or adapting the current `screenshot_sync` command-construction expectations into the new `screenshot sync` surface.
16. Run the sync tests and verify they fail before any sync implementation is added.
17. Implement the minimum sync command path to preserve current behavior.
18. Re-run sync tests until they pass.

19. Write failing tests for `lch` job metadata:
   - job id `lch-screenshot-clipboard`
   - derived launchd label
   - expected dispatch target
   - correct watch path resolution source.
20. Run those `lch` metadata tests and confirm they fail.
21. Implement the smallest `lch` job-definition layer needed to satisfy them.
22. Re-run the metadata tests until they pass.

23. Write failing tests for LaunchAgent plist generation:
   - correct plist path
   - correct label
   - correct `WatchPaths`
   - correct `ProgramArguments`
   - correct stdout and stderr log paths.
24. Run those launchd tests and make sure they fail before implementing install logic.
25. Implement `lch install`, `lch uninstall`, `lch status`, and `lch logs` for `lch-screenshot-clipboard`.
26. Re-run launchd tests until they pass.

27. Write failing dispatch tests for `lch run lch-screenshot-clipboard` to confirm it invokes `screenshot clipboard on-event`.
28. Run the dispatch tests and verify they fail.
29. Implement the dispatch path in `lch`.
30. Re-run the dispatch tests until they pass.

31. Update root workspace membership and root pytest `testpaths` in `pyproject.toml`.
32. Run `uv run pytest` from repo root and confirm the new tests are discovered; if discovery is incomplete, fix workspace or `testpaths` before proceeding.
33. Add docs for `screenshot` and `lch` to `bin/README.md`.

34. Write `bin/screenshot/docs/architecture.md` with diagrams showing internal screenshot config, clipboard history, sync flow, and state ownership.
35. Write `bin/lch/docs/architecture.md` with diagrams showing LaunchAgent generation, label computation, job dispatch, and log paths.
36. Write `bin/lch/docs/screenshot-integration.md` with diagrams showing exactly how `lch` interacts with `screenshot`, including install-time and runtime flows.
37. Verify that all three docs are consistent with the actual implementation and commands.

38. Run package-local tests for `bin/screenshot` and `bin/lch`.
39. Run the full root test suite with `uv run pytest` and do not proceed until all tests pass.

40. Run install smoke checks:
   - `uv tool install ./bin/screenshot --force --no-cache`
   - `uv tool install ./bin/lch --force --no-cache`
   - verify `screenshot --help`
   - verify `lch --help`

41. On macOS, set the Screenshot app save folder to `~/Screenshots`.
42. Install the job with `lch install lch-screenshot-clipboard`.
43. Take one native screenshot and verify the clipboard contains that file path.
44. Take at least five more screenshots and verify:
   - the newest path is on the clipboard
   - `screenshot clipboard list` shows the last 5 copied screenshot paths
   - older entries can be restored with `screenshot clipboard copy --index N`

45. Perform the final verification pass:
   - code matches `plan.md`
   - tests are green
   - smoke checks are green
   - required docs exist with diagrams
   - acceptance criteria are fully met
46. Only stop after the end-to-end implementation, verification, and documentation work is complete.
