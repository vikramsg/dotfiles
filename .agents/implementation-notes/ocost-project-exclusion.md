# ocost project exclusion implementation notes

## Agreed scope

- Add repeatable project exclusion by exact ID, exact canonical path, or unique
  final directory name.
- Remove excluded usage from all terminal and JSON totals and breakdowns.
- Reject unknown and ambiguous selectors.
- Preserve existing options and avoid compatibility behavior.

## Decisions made during implementation

This section records decisions not already agreed with the user and will be
updated throughout implementation.

- Project resolution gives an exact ID precedence over an exact canonical path,
  and either precedence match over a basename. This keeps an ID selector exact
  even if another project's basename has the same text.
- Canonical paths are compared as returned by OpenCode; they are not resolved
  against the local filesystem. This avoids changing remote or unavailable
  paths and matches the API's canonical identifier.
- The report adjustment deep-copies the overall response, subtracts selected
  project counters, costs, tokens, and matching model usage, then removes the
  selected project rows. Unconsumed API fields remain intact rather than being
  guessed or structurally transformed.
- Repeated selectors are idempotent: resolution returns a set of project IDs,
  so a project is subtracted once even if selected repeatedly.
- Project-specific snapshots are fetched before the overall snapshot. Since API
  requests are not atomic, taking the inclusive snapshot last reduces the chance
  that newly recorded usage makes subtraction transiently negative. A rolling
  window can still change at either boundary during collection, so the existing
  reconciliation warning remains applicable.
- The API's daily activity, active-day count, longest streak, and tool-call
  totals are modeled and adjusted because they are usage breakdowns present in
  JSON output. The longest streak is recomputed from the remaining dated
  activity instead of subtracting overlapping project streaks.
- Duplicate overall model identities are combined before excluded model usage
  is subtracted. This preserves accounting if the API emits multiple rows for
  the same provider, model, and variant rather than subtracting from only the
  final duplicate.
- Activity dates are parsed as dates at the model boundary so the adjusted
  longest streak can be derived without putting date interpretation in the CLI
  or renderer. JSON serialization retains the API's ISO date representation.

## Verification record

- `just --justfile bin/ocost/justfile check` passed after the final changes:
  Ruff lint and formatting, plus Ty type checking.
- `just --justfile bin/ocost/justfile test` passed after the final changes: 64 tests, including real
  executable subprocess coverage for selectors, repeated exclusions, adjusted
  JSON/terminal reports, duplicate model identities, activity and tool totals,
  and no-partial-output errors.
- The source distribution and wheel built successfully, and the package was
  installed through the repository's `just ocost` workflow.
- The installed executable was run against the live OpenCode service with one
  exclusion, repeated exclusions, verbose output, JSON output, and an unknown
  selector. Excluded projects stayed absent, invalid input produced empty
  stdout, and parsed JSON retained internally consistent step/activity,
  active-day/streak, and tool-call totals.
- Real TTY output was inspected through Herdr at 147 columns. The compact and
  verbose reports remained readable and contained no excluded project section.
- Adjacent live baseline and excluded reports showed expected small cost and
  step drift while OpenCode was active; counts that did not change reconciled
  exactly. This is the existing separate-request behavior disclosed by the UI.

## Advisory review

- A background reviewer identified that unmodeled activity fields remained
  inclusive and that duplicate model identities could be subtracted from only
  one row. Both findings were accepted because they could produce inconsistent
  JSON accounting under the agreed behavior.
- Activity, active-day, streak, and tool totals are now adjusted, and duplicate
  model rows are combined before subtraction. No speculative compatibility or
  broader refactoring suggestions were adopted.

## What to review

- `ocost/report.py` is the explicit report-composition boundary: it receives
  fully discovered projects and a completed report, with no HTTP or rendering
  dependency.
- Selector precedence is intentional: exact ID, then exact canonical path, then
  a unique basename. A duplicate canonical path is rejected as ambiguous rather
  than selecting an arbitrary row.
- Review the subtraction boundary for all modeled usage: scalar counters,
  tokens, models, dated activity, active-day/streak values, and tool totals.
- Review that duplicate model identity normalization preserves the provider,
  model, and variant distinction used by rendering.
- Unknown future API fields remain preserved but unmodified; review whether any
  newly introduced field represents project-attributable usage before release.
- Review the documented non-atomic snapshot limitation, particularly for
  rolling windows where usage can enter or leave while requests are collected.
