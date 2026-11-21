# Auditing principles for guidance drift

An audit checks whether a principle's mapped members still agree with each other, whether each earns its context cost, and whether attached checks still pass.

## Prerequisites

In git, commit `.principles/maps/ID.json` and all member edits first — `start-audit` bases its audit on `HEAD` and refuses uncommitted maps or member files.

## Full audit workflow

1. **Start the audit:** Run `principles start-audit ID` (writes nothing; prints `request_id`, `context`, and `response_template`). For large requests, inspect `--part index` and read parts selectively with `--part NAME`.
2. **Read every member:** Inspect each member at its mapped path and lines. Check:
   - Actionability, scope, and context cost (especially for always-loaded files).
   - `mapped_elsewhere` overlaps — confirm shared lines have compatible roles across principles.
   - `prior_findings` and `loads_to_check_against_activation` whenever present.
3. **Review and run checks:** If any member names a `check` command:
   - When `check_since_last_audit` is `new` or `changed`, review the command against project documentation or owner approval before running it, and record a one-line `review_basis`.
   - Run the command in the project and record its integer `exit_status` (or `not_run_reason` if it could not run).
4. **Judge delivery honestly:**
   - Mark `observed` only if you saw the mechanism act on real input in this project or read a dated execution record; state what you saw and what you did not see.
   - Reading source or config alone is `not_observed`.
5. **Check one recent decision:** Assess one recent project decision under this principle against the members' own words, or provide an honest `unavailable_reason`.
6. **Submit the assessment:** Write the filled JSON (following `response_template` and `answer_guide`) to a temporary file and run `principles submit-answer REQUEST_ID --file FILE`.
7. **Handle findings if any:** Submitting findings opens a correction stage rather than completing the audit. Make fixes after the assessment is accepted, run `principles show-open-correction ID` if needed, and submit the correction answer disposing of each finding (`fixed`, `deferred`, `accepted`, or `disagreed`).
8. **Commit and verify:** Commit `.principles/audits/ID.json` and run `principles list-member-problems --short` to confirm exit `0`.

## Single-member acknowledgement (`--member`)

When a single already-audited member changed without altering its meaning (e.g., typo fix or rewording), run `principles start-audit ID --member MEMBER`, verify both before/after quotes keep the meaning, submit the answer, and commit `.principles/audits/ID.json`.
