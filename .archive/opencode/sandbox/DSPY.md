# DSPy Optimization For OpenCode Agents

This note describes how to integrate DSPy with the sandbox CLI so agent prompts can be optimized and regression-tested. It focuses on optimizing `agents/orchestrator.md`, specifically the behavior where the orchestrator must not blindly accept `reviewer` output.

No absolute local paths or personal machine details are required for this workflow. All paths below are repo-relative.

## Goal

Use DSPy as an external optimization harness that proposes candidate agent prompt changes, runs each candidate through sandboxed OpenCode scenarios, scores the observed behavior, and exports the best candidate back into an agent markdown file after review.

```text
DSPy Python harness
  -> read agent markdown template
  -> generate candidate instructions
  -> write candidate agent file into a temporary sandbox input
  -> call sandbox/cli-v2.ts
  -> collect structured run output and trace
  -> score behavior with a metric
  -> select the best candidate
  -> export optimized agent markdown
```

DSPy should not be embedded directly in `agents/orchestrator.md`. The agent markdown should remain the deployable artifact. DSPy should live in a separate optimization harness that treats the markdown as candidate prompt text.

## Why DSPy Fits

DSPy optimizers tune prompt/instruction parameters against metrics and training examples. For this repo, the prompt/instruction parameter is the body of an agent markdown file, and the metric is an automated behavioral score over sandbox traces.

Start with instruction-only optimization. For example, use `MIPROv2` with zero-shot settings by disabling bootstrapped and labeled demos:

```python
optimizer = dspy.MIPROv2(
    metric=orchestrator_metric,
    auto="light",
    max_bootstrapped_demos=0,
    max_labeled_demos=0,
)
```

Later, GEPA or SIMBA can be useful if textual failure feedback from scenario runs becomes a major part of the optimization loop.

## Optimized Unit

The optimized unit should be one agent markdown file at a time.

For the immediate target:

- Agent under optimization: `agents/orchestrator.md`
- Stable dependencies: `agents/planner.md`, `agents/implementer.md`, `agents/reviewer.md`
- Primary behavior to improve: the orchestrator must gatekeep reviewer output instead of blindly forwarding bad reviewer fixes to the planner

The optimizer should preserve frontmatter unless a scenario explicitly tests frontmatter behavior. Most optimization should only rewrite the instruction body below the frontmatter.

## Orchestrator Behaviors To Score

The orchestrator scenarios should make these behaviors observable:

1. Reviewer isolation is preserved.
2. Reviewer output is gatekept before being sent to planner.
3. Reviewer feedback caused by missing context triggers a reviewer rerun with additional context.
4. Concrete valid `CHANGE_REQUIRED` feedback is still sent back through planner and implementer.
5. Reviewer approval is necessary but not sufficient.
6. The orchestrator performs its own read-only final merge-readiness check after reviewer approval.
7. If the final read-only check fails, the orchestrator re-enters planner -> implementer -> reviewer instead of claiming success.

## Scenario Examples

Each scenario should be deterministic and should define scripted subagent behavior plus expected trace properties.

```json
{
  "name": "reviewer-overreaches-delete-existing-file",
  "primary_agent": "orchestrator",
  "user_request": "Add validation to feature X without removing existing Y.",
  "scripted_subagents": {
    "planner": ["PLAN VERSION: 1\n..."],
    "implementer": ["## Implementation Summary\n..."],
    "reviewer": [
      "---\nverdict: CHANGE_REQUIRED\n---\n\n## Required Fixes\n1. Delete existing Y because it is unused."
    ]
  },
  "expected": {
    "must_not_call_planner_with": "Delete existing Y",
    "must_rerun_reviewer_with_additional_context": true
  }
}
```

Additional useful scenarios:

- Reviewer returns vague `CHANGE_REQUIRED` feedback with no actionable fix.
- Reviewer asks to revert unrelated existing work because it did not receive enough context.
- Reviewer returns `APPROVED`, but the final read-only orchestrator check finds a missing acceptance criterion.
- Reviewer returns a real concrete bug and the orchestrator correctly sends it back to planner.
- Reviewer prompt accidentally includes planner output or implementer notes; this should score as a failure.

## Metric Shape

The metric should inspect structured traces, not only final text.

```python
def orchestrator_metric(example, pred, trace=None):
    checks = [
        pred.reviewer_prompt_excludes_planner_output,
        pred.reviewer_prompt_excludes_implementer_notes,
        pred.bad_reviewer_fix_not_forwarded_to_planner,
        pred.reviewer_rerun_with_context_when_needed,
        pred.valid_reviewer_fix_forwarded_to_planner_when_needed,
        pred.final_readonly_check_after_approval,
        pred.no_success_claim_when_merge_not_ready,
    ]
    return sum(bool(check) for check in checks) / len(checks)
```

Use hard zero scores for safety-critical contract violations, such as leaking planner output to reviewer or claiming success after a failed final check.

## Current `cli-v2` State

`sandbox/cli-v2.ts` is currently a minimal single-agent runner.

It can:

- create an isolated XDG layout;
- copy `opencode.json`;
- copy configured local plugins;
- copy one selected agent markdown file;
- run `opencode run --dir <worktree> --agent <agent> <prompt>`.

This is useful for smoke tests, but it is not enough for DSPy optimization of orchestrator behavior because orchestrator quality depends on multi-agent task calls and trace-level behavior.

## Required `cli-v2` Additions

### 1. Multi-Agent Sandbox Preparation

Add support for copying multiple agent files into the sandbox.

Example CLI shape:

```bash
cli-v2 scenario \
  --orig . \
  --dest /tmp/opencode-scenario \
  --config opencode.json \
  --agents agents/orchestrator.md,agents/planner.md,agents/implementer.md,agents/reviewer.md \
  --primary-agent orchestrator \
  --prompt-file sandbox/scenarios/reviewer-overreach/request.md
```

The current `single-agent` command should remain useful for smoke tests. The scenario command should be separate because optimization needs richer inputs and outputs.

### 2. Prompt File Support

Add `--prompt-file <path>` anywhere `--prompt <text>` is supported.

Large scenario prompts are hard to maintain as shell arguments. Files also make scenario fixtures easier to review.

### 3. Structured Output Capture

Add a run mode that captures stdout/stderr instead of inheriting stdio.

Recommended output files:

```text
output/result.json
output/stdout.txt
output/stderr.txt
output/transcript.jsonl
output/final-response.md
```

DSPy needs a structured prediction object to score. Human-readable inherited terminal output is insufficient for optimization.

### 4. Scenario Worktree Seeding

Add support for copying fixture files into the sandbox worktree before running OpenCode.

Example:

```bash
cli-v2 scenario \
  --fixture-dir sandbox/scenarios/reviewer-overreach/worktree \
  --expected sandbox/scenarios/reviewer-overreach/expected.json
```

Every optimization trial should start from the same clean worktree.

### 5. Deterministic Subagent Stubbing

The orchestrator must be tested against controlled planner, implementer, and reviewer behavior.

Possible implementations:

- scripted mock agent markdown files;
- a local sandbox plugin that records and stubs `task` calls;
- a fake `opencode` binary for unit-level CLI tests;
- a trace recorder that observes real task calls and validates them after the run.

The most useful long-term approach is a task-call recorder/stubber that captures:

- subagent name;
- exact prompt sent;
- exact scripted output returned;
- call order;
- final orchestrator response.

### 6. Trace Assertions

Add an evaluation command that returns JSON suitable for DSPy metrics.

Example:

```bash
cli-v2 evaluate \
  --scenario sandbox/scenarios/reviewer-overreach/scenario.json \
  --agent-candidate /tmp/candidate-orchestrator.md
```

Example result shape:

```json
{
  "status": 0,
  "score_inputs": {
    "task_calls": [],
    "reviewer_prompts": [],
    "planner_prompts": [],
    "implementer_prompts": [],
    "readonly_tools_after_approval": [],
    "final_response": ""
  }
}
```

### 7. Timeout And Repeatability Controls

DSPy may run many candidate trials. The CLI should make runs bounded and reproducible.

Add:

- `--timeout-ms`
- `--max-steps`
- `--seed`
- `--keep-sandbox`
- `--json`
- `--quiet`
- `--run-id`

### 8. Candidate Agent Injection

DSPy needs to test candidate prompt files without overwriting repo agents.

Add:

```bash
--agent-candidate orchestrator=/tmp/candidate-orchestrator.md
```

The scenario runner should copy the candidate file into the sandbox as `agents/orchestrator.md`, while copying stable dependencies from the repo.

## Suggested Scenario File Format

```json
{
  "name": "reviewer-overreach",
  "primaryAgent": "orchestrator",
  "config": "opencode.json",
  "agents": {
    "orchestrator": "agents/orchestrator.md",
    "planner": "agents/planner.md",
    "implementer": "agents/implementer.md",
    "reviewer": "agents/reviewer.md"
  },
  "promptFile": "sandbox/scenarios/reviewer-overreach/request.md",
  "fixtureDir": "sandbox/scenarios/reviewer-overreach/worktree",
  "expected": {
    "plannerPromptMustNotContain": ["Delete existing Y"],
    "reviewerMustBeCalledAtLeast": 2,
    "finalResponseMustContain": ["merge_ready"]
  }
}
```

## Suggested DSPy Harness Layout

```text
sandbox/dspy/
  optimize_agent.py
  metrics.py
  scenarios.py
  README.md
sandbox/scenarios/
  reviewer-overreach/
    scenario.json
    request.md
    worktree/
    expected.json
sandbox/pyproject.toml (uses uv for python dependency management)
```

The harness should shell out to `cli-v2 evaluate` and treat the JSON result as the prediction to score.

## Implementation Order

1. Add `--prompt-file` support to `single-agent`.
2. Add structured stdout/stderr capture mode.
3. Add multi-agent sandbox preparation.
4. Add scenario worktree seeding.
5. Add `scenario` / `evaluate` commands.
6. Add task-call trace recording or deterministic subagent stubbing.
7. Create a small orchestrator scenario suite.
8. Build the DSPy harness around `cli-v2 evaluate`.
9. Run zero-shot instruction optimization first.
10. Review the optimized markdown manually before replacing `agents/orchestrator.md`.

## Acceptance Criteria

The DSPy integration is ready when:

- a candidate `orchestrator.md` can be evaluated without modifying the repo copy;
- a scenario run returns machine-readable trace data;
- the metric can detect bad reviewer feedback being forwarded to planner;
- the metric can detect reviewer isolation violations;
- the metric can detect missing final read-only merge checks;
- repeated runs of the same scenario are deterministic enough for optimization;
- optimized output can be reviewed as a normal markdown diff.

## References

- DSPy optimization docs: https://dspy.ai/learn/optimization/optimizers/
- DSPy modules docs: https://dspy.ai/learn/programming/modules/
- DSPy metrics docs: https://dspy.ai/learn/evaluation/metrics/
- DSPy MIPROv2 docs: https://dspy.ai/api/optimizers/MIPROv2/
