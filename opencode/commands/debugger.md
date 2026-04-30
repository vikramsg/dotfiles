---
description: Run debugger and orchestrator workflow with planner, implementer, and reviewer subagents.
agent: orchestrator
subtask: false
---
$ARGUMENTS

First, you must create a reproduction workflow.
Run the planning, implementation and review workflow only to create a temporary script to reproduce the error.
Only once the reproduction is fully complete go to the next workflow.

Once reproduction is complete run the planning, implementation and review workflow with the additional acceptance criteria of
the temporary reproduction workflow to now pass.

**Do not** try to run both debugging and fixing in the same loop. Only once the reproduction loop is complete, do the fixing loop.

