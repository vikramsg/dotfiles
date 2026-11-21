# Drift checks and ongoing setup

Use this guide to detect drift in mapped guidance files between audits and to wire up ongoing reminders or hooks.

## Checking for drift

- Run `principles list-member-problems --short`.
  - Exit `0`: every mapped member matches its audited baseline.
  - Exit `1`: refusal (for example, `broken_members` when a mapped file or section was renamed or deleted) — follow the `repair` and `repair_with` commands printed on stderr (`move-member` or `remove-member`).
  - Exit `3`: at least one member changed or has no completed audit — follow the commands it prints (or drop `--short` for full JSON with `next_action`; see [changing-rules.md](changing-rules.md) and [auditing-principles.md](auditing-principles.md)).
- Run `principles list-open-findings` to view deferred or accepted findings carried over from completed audits.

## Setting up the meta-principle (`sticking-to-your-principles`)

To instruct every agent session to run drift checks automatically:

1. Run `principles show-meta-principle-passage`.
2. Show the proposed passage to the user and agree on the always-loaded entry file (such as `AGENTS.md` or `CLAUDE.md`).
3. Place the passage verbatim without altering its words; add any repo-specific install/link note as a separate sentence afterward if agreed.
4. Map it with the `principles add-member sticking-to-your-principles ...` command printed in `answer_with` (this creates `.principles/maps/sticking-to-your-principles.json`).
5. Commit both the edited entry file and `.principles/maps/sticking-to-your-principles.json`, then run `principles start-audit sticking-to-your-principles`.

## Setting up hooks

Run `principles show-hook-setup` to view session-start (`principles report-at-session-start`) and post-commit (`principles report-after-commit`) hook configurations. Show the entries to the user and only write or merge them into settings after agreement (avoid committing hooks that fail for teammates who do not have `principles` installed).
