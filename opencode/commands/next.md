---
description: Tell me next steps 
agent: build 
subtask: false
---
$ARGUMENTS

Give me a to-do list of everything you will do. 
After checks and tests are all complete, push and create a PR.

## PR description

You will not give implementation details but the simplest summary of what actually you did
- Prefer bullet points to separate out main features of the PR 
- For the PR description, if there has been update, give the updated description while sticking to these principles 

### Reminder

Do not include stuff like this in the PR description. These are implementation notes not PR description.

```
## Verification

- Backend formatting, lint, and static analysis passed.
- <N> backend tests passed with <M> coverage.
```

## Implementation Notes

You will maintain implementation notes in a markdown file and at the end add a section for what I should look for in a review.
- Put the notes in .agents/implementation-notes/ 
- Write every decision you took that we did not already agree on
- Write every single decision that requires a review. 
- At the end of the notes write what should be specifically reviewed by me 

NOTE: If we have agreed to a plan, make sure its present in .agents/plans/ and in it note that once we start implementation the plan file itself should not be touched and any changes should be only noted through implementation notes

## Testing hygiene

- You will only write behavioural tests, not change detections tests
- You will not automate tests that you have to verify manually

## Naming and Code comment hygiene

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


## Implementation hygience

- Never add fallback, compatibility, backward shims unless already discussed.
- Prefer using background agents for implementation and review but note they do not have full context so review their output before accepting

## Review

After all checks and tests pass launch a background reviewer agent. Make sure it's in the background. 
But do not let the reviewer be authoritative. Its an advisory agent. 
The reviewer is prone to trying to suggest over-engineering, over defensive, etc. which you should not blindly follow.

However some things we are interested in from the review
- Could the implementation have been simplified
    - Make the reviewer really try to come up with simplifications, since you are prone to just add instead of reuse and refactor.
- Are we following the correct layer rules

## Reply right now

1. Your ToDo list
2. PR description
3. What review points will be allowed to make you change your implementation 
4. What tests will you write, how will you maintain testing hygiene and how will you verify e2e.
5. How will you maintain code comments, documentation and naming hygiene

