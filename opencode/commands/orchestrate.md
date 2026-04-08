---
description: Run the hidden orchestrator workflow with planner, implementer, and reviewer subagents.
agent: orchestrator
subtask: false
---
$ARGUMENTS

Drive a strict planner -> implementer -> reviewer workflow.

Requirements:
- Start with the `planner` and require a PR-style plan before any implementation work begins.
- The plan must include: `Executive Summary`, `Architecture and Data Flow`, `Impact Matrix`, `Acceptance Scenarios (BDD)`, `Highest-Risk Review Points`, and `Implementation Checklist`.
- The plan must include both a mandatory ASCII diagram and a mandatory Mermaid diagram.
- Pass the latest approved planner output into `implementer`.
- Require `reviewer` to perform a deep critical pass that checks best practices, needless fallback logic, over-mocked tests, and Next/React guidance when relevant.
- If the reviewer returns `VERDICT: FAIL`, extract the concrete required fixes, send them back through replanning, then re-run implementation and review until the reviewer returns `VERDICT: PASS`.
- If the user explicitly asks for a no-edit, inspect-only, or hypothetical workflow demonstration, keep the same planner -> implementer -> reviewer order but run it in strict dry-run mode: no file edits, only safe read-only verification, and a reviewer `VERDICT: PASS` is allowed for a complete workflow demonstration.
- In strict dry-run mode, scope the work to the exact prompt files named in the request plus any explicitly named reference prompts.
- For the dry-run smoke path, compare the hidden orchestrate prompt stack against `opencode/commands/planner.md` and `opencode/commands/g-review.md` only, and treat `opencode/commands/fplanner.md` as out of scope unless the user explicitly asks for repo-wide planner alignment.

Do not treat this command as a thin passthrough. The orchestration should explicitly depend on the structured planner output and the reviewer pass/fail loop.
