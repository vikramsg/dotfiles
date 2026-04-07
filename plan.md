## Goal

Implement a high-reliability, no-plugin orchestrator workflow for OpenCode using:

- a hidden primary `orchestrator` agent
- hidden `planner`, `implementer`, and `reviewer` subagents
- a slash command entrypoint
- prompt contracts that force a sequential planner -> implementer -> reviewer loop until the reviewer returns `VERDICT: PASS`

This is intentionally prompt-driven rather than deterministic engine control. The design aims to be as reliable as possible while staying within current upstream OpenCode capabilities.

## Constraints

- No plugin orchestration layer
- No fake verification
- Verification must include a live orchestration run on a real fixture with executable tests
- Hidden primary entrypoint must be slash-command driven
- Planner, implementer, and reviewer must be callable through `task`
- The orchestrator should behave as a coordinator rather than a general-purpose coding agent

## Implementation Plan

1. Add a hidden primary `orchestrator` agent in `opencode/agents/orchestrator.md`.
2. Add hidden subagents in `opencode/agents/`:
   - `planner`
   - `implementer`
   - `reviewer`
3. Add `/orchestrate` command in `opencode/commands/orchestrate.md` that routes directly to the hidden `orchestrator` primary agent.
4. Update `opencode/opencode.json` agent overrides so visible built-in primary agents do not expose the new orchestration subagents through `task`.
5. Use strict output contracts:
   - planner returns versioned plan + acceptance criteria + verification commands
   - implementer returns changed files + commands run + real results
   - reviewer re-runs relevant verification and returns `VERDICT: PASS|FAIL`
6. Make the orchestrator loop instructions explicit:
   - start with planner
   - pass planner output to implementer
   - pass planner + implementer output to reviewer
   - if reviewer fails, feed the failure back into planner and continue
   - stop only when reviewer says `VERDICT: PASS`

## Acceptance Criteria

1. `opencode agent list` shows the new agents load successfully.
2. `/orchestrate` resolves to the hidden orchestrator agent.
3. The built-in visible primary agents do not expose `planner`, `implementer`, or `reviewer` as usable `task` subagents.
4. A live orchestration run can modify a real fixture and make its executable tests pass.
5. The orchestration run ends only after the reviewer returns `VERDICT: PASS`.

## Verification Plan

1. Run `opencode agent list` to confirm all agents load.
2. Run a command-driven orchestrator invocation with `opencode run --command orchestrate ...`.
3. Use a temporary in-repo fixture with a genuinely failing test before the run.
4. Confirm the fixture test fails before orchestration.
5. Run the orchestrator and inspect JSON event output to confirm task usage and reviewer pass.
6. Re-run the fixture test after orchestration and confirm it passes.
7. Check the resulting session or run output for evidence that planner, implementer, and reviewer all executed.

## Risk Notes

- The loop is prompt-driven, so step ordering is not engine-enforced.
- Reliability depends on strong prompt contracts and reviewer strictness.
- A live verification fixture is necessary because static config validation alone is not enough.
