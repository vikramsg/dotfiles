---
description: Tell me next steps 
agent: build 
subtask: false
---
Okay, give me a to-do list of everything you will do. 
What you should do after checks and tests are all complete, you should push and create a PR.

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

## Implementation hygience

- Never add fallback, compatibility, backward shims unless already discussed.
- Prefer using background agents for implementation and review but note they do not have full context so review their output before accepting

## Review

After all checks and tests pass launch a background reviewer agent. Make sure it's in the background. 
But do not let the reviewer be authoritative. Its an advisory agent. 
The reviewer is prone to trying to suggest over-engineering, over defensive, etc. which you should not blindly follow.

However some things we are interested in from the review
- Could the implementation have been simplified
- Are we following the correct layer rules

## Reply right now

1. Your ToDo list
2. PR description
3. What review points will be allowed to make you change your implementation 
4. What tests will you write, how will you maintain testing hygiene and how will you verify e2e.

