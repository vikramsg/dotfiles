# ocost project exclusion plan

## Goal

Add a repeatable `--exclude-project PROJECT` option to `ocost` that removes
selected projects from terminal and JSON reports, including overall costs,
activity, token totals, and model totals.

## Agreed behavior

- Accept exact project IDs and canonical paths.
- Accept a canonical path's final directory name only when it identifies one
  project uniquely.
- Reject unknown and ambiguous selectors instead of silently ignoring them.
- Allow multiple exclusions by repeating `--exclude-project`.
- Exclude selected projects from compact output, verbose output, and JSON.
- Adjust the overall totals and model breakdowns rather than only hiding rows.
- Preserve existing `--days`, `--json`, and `--verbose` behavior.
- Add behavioral tests only; keep subjective terminal checks manual.
- Add no fallback, compatibility alias, or backward-compatibility shim.

## Work

1. Tidy the report composition boundary so project resolution and adjusted
   report construction are explicit and testable outside rendering and HTTP.
2. Implement selector resolution and report adjustment.
3. Wire the repeatable Click option into the CLI.
4. Update user-facing documentation with concise examples and selector rules.
5. Add executable-level behavioral coverage for selection, accounting, output
   formats, repetition, ambiguity, and errors without partial output.
6. Run package tests, formatting, lint, type checks, build, installation, and
   live end-to-end verification.
7. After checks pass, launch a background advisory review focused on
   simplification and layer boundaries; assess findings rather than accepting
   them automatically.
8. Commit, push, and create a pull request with a concise user-facing summary.

## Change control

Once implementation starts, this plan file must not be changed. Any discoveries,
deviations, or additional decisions must be recorded only in
`.agents/implementation-notes/ocost-project-exclusion.md`.
