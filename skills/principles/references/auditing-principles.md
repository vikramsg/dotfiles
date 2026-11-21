# Auditing principles for guidance drift

An audit checks whether a principle's mapped members still agree with each other. In git, commit `.principles/maps/ID.json` and any member edits first—`start-audit` refuses uncommitted map or member files.

## Full audit

1. Run `principles start-audit ID` and follow its `question`, `answer_guide`, and `response_template` (for large requests, use `--part index` and `--part NAME`).
2. Read each member where the map locates it. If a member lists a `check` command, review it before running when `check_since_last_audit` is `new` or `changed`, then run it and record its exit status.
3. Mark delivery `observed` only when you saw the mechanism act on real input or read a dated execution record—reading source alone is `not_observed`.
4. Submit your filled JSON with `principles submit-answer REQUEST_ID --file FILE`. If you raised findings, complete the correction stage (`show-open-correction ID`) before the audit finishes.
5. Commit `.principles/audits/ID.json` and confirm `principles list-member-problems --short` exits `0`.

## Wording-only edits

When one already-audited member changed without altering its meaning, commit the edit, run `principles start-audit ID --member MEMBER`, submit the answer, and commit `.principles/audits/ID.json`.
