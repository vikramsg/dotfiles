---
description: Run orchestrator workflow with planner, implementer, and reviewer subagents.
agent: rigorchestrator
subtask: false
---
$ARGUMENTS

1. Do not remove pre-existing changes from the PR except what is exactly agreed
2. Every decision you make that is not directly in the plan, record in implementation_notes.md for me to review at the end. It should exist but no git operations.
    - Track which plan version is being used in the notes
    - Make sure the doc is append only with roughly the format
    ```
    ### PLAN VERSION: 1

    - Decision: <decision not directly specified in the user plan>
      Reason: <why it was needed>
      User review: <what the user should confirm>
   ```
3. Do not do git mutations operations unless I have specifically asked you to do it
4. If the planner or reviewer makes suggestions aginst the agreed intent, rerun them with correct context
    - Remeber agents like planner and reviewer have ONLY the context you provide them and do not have access to previous conversations or sessions.
    - Remember the planner and reviewer instructions are advisory and do not apply if they suggest out of scope changes.
    - Therefore, if either the planner or reviewer suggest doing out of scope changes, reject and rerun
5. Make sure to add code comments and docstrings where appropriate. DO NOT add obvious code comments but make sure they are self-sufficient and does not need understanding a concept that is not already there in the surrounding code

