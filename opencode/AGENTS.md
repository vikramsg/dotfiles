## Safety Rule

Never delete any .sqlite or .db database files. If a task requires deleting them, abort and inform the user.

NOTE: DO NOT jump to implementation if the current conversation is discussion. Your job is NOT to jump to solutions. First, via a discussion, you must make sure the user is satisfied with 
    - your understanding of the problem
    - how you are going to solve the problem.

## Conversation hygiene

- Never use the phrase "You are right" or similar.
    - Your job is not to reply with this phrase. 
    - It is better to either
        1. Disagree if something is wrong with the statement and state why
        2. If you do not disagree then state what you need to do without using that phrase
- Walls of text are never helpful. Always prefer shorter responses.
- Speak Human
- NOTE: Disagreeing is not an option if the user says to `do` or `build` something.

## Engineering Approach

- Apply a `Tidy, First` lens: consider whether a small preparatory refactor would make the intended change easier and safer. Make the change easy, then make the easy change.
- When planning, explain how the approach applies `Tidy, First` principles and prefer a dedicated section when useful.
- When recording implementation notes for out-of-plan work, include how `Tidy, First` principles informed the implementation.

## OpenCode hygiene

NEVER switch to a different worktree unless asked.
I am launching you from a workspace because I want to follow code changes.
By changing to a worktree in a different location you are making it harder to work.

## PR scope

- When I ask you to create a PR, include all current staged and unstaged changes, including changes you did not author, unless I explicitly limit the scope.
- Do not silently exclude changes because they appear unrelated or user-authored. If you have a concrete concern about including something, ask before proceeding.
- In your final response, identify included changes you did not author by file and briefly describe them. If there are none, say so.
- PR description should never have things like Verification done on local machine unless explicitly asked. 

## Plans

If the user asks for a plan as a file, always put in `.agents/plans/`.

## Implementation hygiene

- Never add fallback, compatibility, backward shims unless already discussed.
- Prefer using background agents for implementation and review but note they do not have full context so review their output before accepting
- When implementing/building make sure to follow [Implementation Notes](#implementation-notes).
- Prefer launching shell commands in parallel where feasible.
    - Prefer running shell commands in background so that the user can continue interacting with you while you are waiting for commands to complete.

### Implementation Notes

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

## Review focus

- <what I should look at specifically>
- Reviewer-driven changes: <list, or "none">
```

NOTE: If we have agreed to a plan, make sure its present in .agents/plans/ and in it note that once we start implementation the plan file itself should not be touched and any changes should be only noted through implementation notes

## Testing hygiene

- You will only write behavioural tests, not change detections tests
- You will not automate tests that you have to verify manually

## Naming and Code comment hygiene

### Documentation hygiene

- Documentation files must be operational documentation, without conversation history, implementation-plan links, agent progress, or test-result reports.
- Never use artificial 80 column limits for writing code comments, docs etc

### Code comment and Docstring hygiene

- Explain what the code cannot readily tell the reader: reasons, constraints, and consequences.
- Use concrete domain terms rather than vague architectural language.
- Write for a developer unfamiliar with our earlier discussions.
- Describe the actual behavior; update explanations affected by code changes.
- Use enough detail. Shorter is not automatically clearer.
- Use lists, examples, tables, or diagrams when they reduce reading effort.
- Remove comments that merely repeat the code.

### Naming

- Name what a value contains or what a function does.
- Use clear domain terminology and distinguish easily confused concepts, such as raw IDs versus stable IDs.
- Make conversion direction, units, and side effects clear where relevant.
- Avoid vague qualifiers such as scoped, resolved, or normalized unless their meaning is clear in context.
- Prefer a better name over a comment explaining a poor name.
- Do not lengthen names unnecessarily; judge clarity at the call site.


## Review

After all checks and tests pass launch a background reviewer agent. Make sure it's in the background. 
Note that the review is advisory. 
The reviewer is prone to trying to suggest over-engineering, over defensive, etc. which you should not blindly follow.
Do not overconstrain the reviewer in the review prompt, otherwise the reviewer is prone to just agreeeing with whatever you asked it to do.

Some things of special interested in from the review
- Could the implementation have been simplified
    - Make the reviewer really try to come up with simplifications, since you are prone to just add instead of reuse and refactor.
- Are we following the correct layer rules
- Do the documentation and code comments are at appropriate places. Do they sound like a human and not an agent.
- Is the implementation follow existing patterns or is it inventing new ones without agreeing to in the plan

