# Standalone ocost implementation notes

## Scope and decisions

The command replaces the shell report with a small Python package that uses
`httpx2` directly. It reads OpenCode V2's project and statistics endpoints and
does not reconstruct accounting from session histories. ocint is only a visual
reference: no imports, shared code, or changes to that tool are needed.

The CLI resolves the registration path and captures the current instant. Both
are passed explicitly to the code that consumes them. The API receives a client;
the renderer receives report data, a window, and a width. Configuration lookup
belongs at the CLI boundary, not inside discovery or other lower-level behaviour.

The local service's Basic authentication was verified with curl. The client
uses username `opencode` and the password from the supplied registration file.
It restricts the destination to a local HTTP endpoint, disables proxy environment
lookup and redirects, and avoids echoing raw validation or network errors that
could contain secrets. It does not manage the service lifecycle.

The consumed API fields are validated strictly. Extra response fields remain
available in JSON, and absent optional fields are not filled in during export.
Project discovery must contain unique IDs, and each statistics response must
match the requested range. Separate requests are not an atomic snapshot; cost
discrepancies are disclosed, not silently corrected.

## Tidy, First

The small preparatory step was separating API validation, time-window calculation,
and presentation before composing the report. No shared framework or ocint
refactor was introduced. During implementation, registration lookup was moved
from discovery to the CLI boundary. This made discovery tests ordinary file-input
tests and removed environment monkeypatching rather than adding another abstraction.

## Branch and shell migration

The original checkout's `smt3` history combined the earlier shell helper with an
unrelated Neovim change. This work uses a clean worktree based on `origin/main`,
which never contained that shell helper. The PR therefore does not include the
unrelated change or an artificial add/remove cycle for the shell code.

The old helper and its superseded tests/docs are removed separately from the
original linked checkout. Those removals are not part of the main-based PR;
they were subsequently included in that checkout's independently created commit
`e528b86`. This PR does not carry that unrelated Neovim commit.
Already-running shells must drop their loaded function once, as documented in
the user guide; fresh shells resolve the installed executable directly.

## Verification record

- Behavioural suite: 53 passing cases after the CLI-boundary refactor.
- Formatting, lint, and type checks passed through the package `justfile`.
- Source distribution and wheel built; installed command ran successfully from
  outside the repository against the live service.
- Local-midnight tests cover UTC, Asia/Kolkata, and both Los Angeles DST changes.
  A subprocess with an explicit timezone is used because this Python build does
  not expose `time.tzset()`.
- Tests use injected HTTP transports for failures and a real temporary HTTP
  server for executable-level checks. No environment monkeypatches or visual
  snapshot/change-detection tests are used.
- Authenticated curl comparisons used each report's exact time bounds for
  all-time, today, and seven-day output. Complete overall/project responses
  matched, and all eight projects reconciled costs, counts, and token categories.
  Totals naturally change as OpenCode continues working. An initial comparison
  made alongside other live checks changed between reads; serial comparisons
  then matched. No service state was changed to obtain a stable result.
- Herdr inspection at 80 and 160 columns confirmed styling, numeric alignment,
  wrapping, and zero-cost model visibility. The narrow layout was changed from
  positional token values to explicit labels after inspection. A manual
  long-label fixture confirmed full identities wrap in tables (section rules
  abbreviate overlong headings). No screenshot or whitespace snapshots were added.
- Piped JSON parsed successfully; an isolated missing-registration invocation
  returned exit 1 with empty stdout. The actual service registration was untouched.
- The old zsh function/helpers and superseded README/test were removed from the
  original checkout. `zsh -n` passes, and fresh-shell lookup resolves the installed
  executable. Unrelated Neovim edits were left untouched.
- Installation uses `--no-cache` so edits to package source are rebuilt rather
  than reusing an earlier local wheel. The final source distribution/wheel built.
- All 53 cases also passed against the built wheel in a fresh isolated environment
  outside the repository, using newly resolved dependencies rather than the
  workspace environment. A fresh interactive zsh resolves the installed command.

## Advisory review

The background review is requested only after checks, tests, and live/manual
verification pass. Findings are advisory: concrete correctness, security,
usability, scope, and behavioural coverage issues warrant changes; speculative
frameworks, compatibility layers, and broad refactors do not.

The background reviewer completed a read-only staged-diff review and independently
ran the package checks and all 53 tests successfully. It reported no blocking or
actionable non-blocking findings. No implementation changes were made on its
authority; the implementation was retained based on the behavioural checks,
live comparisons, and manual inspection described above.

## What to look for in review

1. Configuration is resolved at the CLI boundary and dependencies are explicit.
2. Credentials stay local and out of diagnostics; requests remain read-only.
3. Date bounds, project attribution, zero-cost usage, and JSON data are preserved.
4. The report is readable at normal and narrow widths without losing identities.
5. Tests assert behaviour, not implementation shape, and visual checks remain manual.
6. The change stays standalone and does not carry unrelated work into the PR.
