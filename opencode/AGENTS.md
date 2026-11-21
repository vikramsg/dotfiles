## OpenCode hygiene

NEVER switch to a different worktree unless asked.
I am launching you from a workspace because I want to follow code changes.
By changing to a worktree in a different location you are making it harder to work.

## Plans

If the user asks for a plan as a file, always put in `.agents/plans/`.

Maintain implementation notes in a markdown file and at the end add a section for what I should look for in a review.
- Put the notes in .agents/implementation-notes/ 
- Write every decision you took that we did not already agree on
    - Separate out each decision as a separate list item with sublist on decision, why and where in code you took it
- Write every single decision that requires a review. 
- Also write every change made because of reviewer guidance or because I asked for it during implementation and it is not in the agreed plan
- Tag every decision with its source:
    - `agent`: you decided it on your own
    - `reviewer`: you accepted a suggestion from the reviewer agent
    - `user`: I asked for it during implementation
- At the end of the notes write what should be specifically reviewed by me, and list the reviewer-driven changes separately

Use this template:

```markdown
## Decisions

- <Short title of the decision>
    - Decision: <what was done>
    - Why: <reason>
    - Where: <file:line or module>
    - Source: agent | reviewer | user
    - Origin: <only for reviewer/user: one line on what was suggested or asked>
<newline>
- <Next decision>




