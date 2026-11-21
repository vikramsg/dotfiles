# Stick to your principles (compliance audit)

Use this workflow to verify whether an agent's actual work (current diff, branch commits, PR title/description, tests, docs, or workflow) complied with the repository's mapped principles. This audits **the change itself**, whereas [auditing-principles.md](auditing-principles.md) audits whether guidance files agree with each other.

## Steps

1. **List mapped principles:** Run `principles list-principles` to see every principle mapped in this repository.
2. **Establish the scope under review:** Inspect the concrete artifacts being evaluated — e.g., `git diff <base>..HEAD`, `git status`, commit messages, PR title/description, or newly authored files. Treat the author's explanation as non-evidence; judge from the actual diff and files.
3. **Read applicable members directly:** For each principle relevant to the scope, run `principles show-principle ID` and read the mapped passages at their exact paths and line ranges. Do not judge from the one-line principle description alone.
4. **Run attached checks:** If an applicable member declares a `check` command, review it before running if unfamiliar, then execute it and record its exit status and output.
5. **Check for unacknowledged guidance drift:** Run `principles list-member-problems --short`.
   - If it exits `3`, report every changed, broken, or unaudited member as a violation/action item so the change does not leave mapped guidance out of sync.
6. **Report compliance per principle:** For each mapped principle, report one of `pass`, `violation`, or `not applicable`:
   - **Violations:** Cite the principle ID, exact member path/section, offending file:line (or commit/PR field), what rule was broken, and the concrete fix.
   - **Checks run:** Include commands executed and their results.
   - **Drift status:** Include the `principles list-member-problems --short` exit status and any reported members.
