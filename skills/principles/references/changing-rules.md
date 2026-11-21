# Changing a rule the project holds

When asked to change a rule, update every member that carries it rather than only the file you were pointed at.

## Checklist

1. **Locate every carrier:** Run `principles list-principles`, then `principles show-principle ID` to inspect every mapped member. If no principle carries the rule yet, edit the guidance and map it using [creating-principles.md](creating-principles.md).
2. **Update the whole set:** Edit every member touched by the change (instructions, review checklists, scripts, tests, CI workflows) so all of them still agree before moving on.
3. **Check for problems:** Run `principles list-member-problems --short` and follow what it reports:
   - **Broken locator (`locator_lost` / renamed file):** Repair with `principles move-member` or `principles remove-member`.
   - **Changed member:** Commit the member edits (and any map repairs) in git first — `start-audit` refuses uncommitted member or map files.
     - **Wording/formatting edit only (same meaning):** Acknowledge that member with `principles start-audit ID --member MEMBER` and submit the meaning-kept answer.
     - **Meaning changed:** Run a full audit via [auditing-principles.md](auditing-principles.md).
4. **Verify clean state:** Repeat until `principles list-member-problems --short` exits `0`, then summarize what each member now says.
