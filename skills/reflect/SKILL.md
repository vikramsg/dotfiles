---
name: reflect
description: Diagnose why an agent—either yourself or another OpenCode session/subagent—made a mistake, missed something, or took an unexpected decision. Use when asked to reflect on why something happened or to ask a finished subagent or session why it acted the way it did. Strictly diagnostic; does not apologize or fix files.
---

# Reflect

Find out *why* an agent produced a specific output or missed something, grounded in the context it actually saw.

## Rules

- Do not apologize.
- Do not edit files, fix the issue, or jump to solutions.
- Do not lead the subject with hints about what it "should" have noticed.

## Reflecting on yourself

Trace the exact decision back to the context you actually had:
- Which local files, instructions (`AGENTS.md`, rules, skills), and tool outputs you read—and which you skipped or never loaded.
- Which external or built-in context (harness instructions, defaults, assumptions) shaped the choice.
- Where the context was missing, ambiguous, or contradictory.

## Reflecting on another session or subagent

- If you have its `sessionID` (for example a finished subagent), follow up with that session directly (`subagent` with `sessionID`) and ask it to explain why it made the specific decision, without apologizing or changing anything, citing the exact files, instructions, skills, and context it actually read.
- If it is another OpenCode session without a live subagent handle, inspect its transcript via `opencode api get /api/experimental/session/<sessionID>/export` to see what context and tool outputs it actually loaded.
- Report the root cause back concisely so the user can decide whether anything needs to change.
