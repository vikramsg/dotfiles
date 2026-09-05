# CLI grouping and Macflow skill

## Scope and Tidy First

- Reuse existing Swift Argument Parser leaf commands and request plans; add
  responsibility groups rather than rewriting the CLI or HTTP API.
- Keep capture separate from presentation. `--preview` remains an explicit
  convenience. Native/WebKit renderer unification is not part of this change.
- Move existing README material into focused action/UI guides and link existing
  configuration and API references rather than duplicating them.
- Keep the skill and linking implementation in `bin/macflow/`. The root installer
  supplies `~/.config/opencode/skills/macflow` to the package's `link-skill`
  recipe; linking runs only on macOS.

## Compatibility

- Flat CLI names are replaced, not retained as aliases. The migration guide
  covers every previous command. Argument and HTTP contracts stay unchanged.
- Update installer health checks and diagnostic recovery suggestions together
  with the command hierarchy, so they remain executable.
- `ui shelf show` still takes a directory and opens the native shelf. It does
  not yet select a configured shelf name or WebKit renderer.

## Verification

- Swift Testing: 96 tests pass. Release build succeeds. Existing request-plan
  tests cover every regrouped leaf; additional checks cover group help, nested
  argument errors, and capture's explicit preview opt-in. No visual snapshots
  or private implementation-sequence assertions were added.
- Real CLI against an isolated HTTP fixture: unauthenticated health,
  authenticated diagnostics, denied-permission guidance, HTTP errors, and
  unavailable-service failures pass. This did not change live permissions.
- Signed-app update: backed up the installed app/CLI, stopped the existing
  launchd job, replaced only executables, preserved the designated requirement,
  verified the signature, and restarted the same job. Doctor passes all five
  checks; Accessibility and Screen Recording remain granted.
- Fingerprints confirm live Macflow config contents and symlinks are unchanged.
- Manual terminal check: root/UI/shelf/capture help and doctor render correctly.
- Live commands: app/window/screen inspection; window frame/focus/unminimize;
  all four configured maximize/column hotkeys and their resulting geometry and
  active application; PNG capture, display selection, preview opt-in, overlay
  show/list/hide and exclusion during capture; native shelf show/list/close;
  WebKit hotkey, rendering, and Escape. HTTP and parsing failures report stderr
  and nonzero status. Ghostty's original frame is restored and the test-created
  empty Zed window is closed.
- Installer exercised with an isolated HOME: Darwin links the expected source,
  repeat installation works, Linux is a no-op, and a preexisting real directory
  is preserved with an error. The Linux check simulates `uname`, not a Linux host.
- OpenCode discovery verified through `opencode2 api get
  "/api/skill?location%5Bdirectory%5D=$PWD"`: ID `macflow`, location
  `~/.config/opencode/skills/macflow/SKILL.md`, and exact skill body match.
  Resource discovery is asynchronous; a fresh API call can briefly list no skills.
- Local documentation links resolve; `git diff --check` passes.

Local backups, fingerprints, error results, and screenshots are in the temporary
`macflow-groups-e2e.OYGoco` directory under the approved OpenCode temp directory.
No desktop screenshots are committed or uploaded.

## Limitations and follow-up

- A Finder test encountered a focus change: a temporary path was typed into
  another agent pane. Reported to the user and stopped synthetic typing. A new
  real-file drag/delivery check was not completed in this pass; successful drag
  verification from the earlier merged refactor is historical evidence only.
- Tidy First for this testing discovery: strengthen the existing skill's input
  guidance to recheck focus and stop on an active shared desktop, rather than
  introducing new input orchestration or changing runtime behavior here.
- No real TCC revocation or permission prompts were exercised. Permission-denied
  behavior was checked with HTTP fixtures and the existing runtime test suite.
- Shelf renderer dispatch, stable window IDs, drag-completion acknowledgement,
  and uniform configuration reload remain separate scope.

## Advisory review

- A separate OpenCode agent reviewed the diff in a background Herdr tab, reran
  the targeted CLI/diagnostics tests (18 passed), and reported no blocking issues.
- Accepted its concrete documentation finding: the skill's short command paths
  needed an explicit instruction to prefix them with `macflow`. Added that once
  rather than expanding every example or introducing new documentation layers.
- Review confirmed the HTTP contracts, migration coverage, installer health
  checks, diagnostic suggestions, and macOS-only skill guard. No speculative
  architecture changes were proposed or needed.

## Installation ownership correction

- User feedback: the root justfile should supply the skill destination, not own
  the linking implementation. Moved the existing logic into the package-local
  `link-skill target` recipe; root `macflow` now delegates with the default path.
- Tidy First: move and parameterize the existing recipe rather than introduce a
  new installer abstraction. Retain the macOS guard and existing-directory safety.
- Verification passed in an isolated HOME: a custom destination containing
  spaces, quotes, and a dollar sign; repeat linking; simulated Linux no-op;
  protection of existing directories/files; and root delegation of the default
  destination and installation to the package. No live configuration or service
  was touched. Recipe discovery and `git diff --check` also pass.

## What to review

- Are responsibilities discoverable without cluttering the root help?
- Do existing leaf commands retain their arguments, defaults, requests, and output?
- Do the docs and skill describe available behavior rather than roadmap ideas?
- Is skill linking macOS-only and limited to the requested destination?
- Do tests verify observable behavior rather than snapshots or private sequences?
