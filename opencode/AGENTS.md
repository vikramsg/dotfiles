## Safety Rule

Never delete any .sqlite or .db database files. If a task requires deleting them, abort and inform the user.

## Conversation hygiene

- Never use the phrase "You are right" or similar.
    - Your job is not to reply with this phrase. 
    - It is better to either
        1. Disagree if something is wrong with the statement and state why
        2. If you do not disagree then state what you need to do without using that phrase
- NOTE: Disagreeing is not an option if the user says to `do` or `build` something.

## Engineering Approach

- Apply a `Tidy, First` lens: consider whether a small preparatory refactor would make the intended change easier and safer. Make the change easy, then make the easy change.
- When planning, explain how the approach applies `Tidy, First` principles and prefer a dedicated section when useful.
- When recording implementation notes for out-of-plan work, include how `Tidy, First` principles informed the implementation.

## Plans

If the user asks for a plan as a file, always put in `.agents/plans/`.

## Implementation hygiene

- Never add fallback, compatibility, backward shims unless already discussed.
- Prefer using background agents for implementation and review but note they do not have full context so review their output before accepting
- When implementing/building make sure to follow [Implementation Notes](#implementation-notes).

### Implementation Notes

Maintain implementation notes in a markdown file and at the end add a section for what I should look for in a review.
- Put the notes in .agents/implementation-notes/ 
- Write every decision you took that we did not already agree on
    - Separate out each decision as a separate list item with sublist on decision, why and where in code you took it
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


## Review

After all checks and tests pass launch a background reviewer agent. Make sure it's in the background. 
But do not let the reviewer be authoritative. Its an advisory agent. 
The reviewer is prone to trying to suggest over-engineering, over defensive, etc. which you should not blindly follow.

Some things of special interested in from the review
- Could the implementation have been simplified
    - Make the reviewer really try to come up with simplifications, since you are prone to just add instead of reuse and refactor.
- Are we following the correct layer rules


