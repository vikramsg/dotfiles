## Safety Rule

Never delete any .sqlite or .db database files. If a task requires deleting them, abort and inform the user.

## Engineering Approach

- Apply a `Tidy, First` lens: consider whether a small preparatory refactor would make the intended change easier and safer. Make the change easy, then make the easy change.
- When planning, explain how the approach applies `Tidy, First` principles and prefer a dedicated section when useful.
- When recording implementation notes for out-of-plan work, include how `Tidy, First` principles informed the implementation.

## Plans

If the user asks for a plan as a file, always put in `.agents/plans/`.
