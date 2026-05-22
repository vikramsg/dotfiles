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

`sandbox/cli-v2.ts` now supports single-agent smoke runs plus deterministic scenario/evaluate runs that produce structured artifacts for scoring.

It can:

- create an isolated XDG layout;
- copy `opencode.json` and configured local plugins;
- copy one selected agent markdown file for `single-agent` runs;
- load prompts from `--prompt` or `--prompt-file`;
- run `opencode run --dir <worktree> --agent <agent> <prompt>`;
- capture structured output files under `output/`, including `result.json`, `stdout.txt`, `stderr.txt`, `status.json`, `metadata.json`, `final-response.md`, `transcript.jsonl`, and `evaluation.json`;
- prepare multi-agent scenario sandboxes from `scenario.json` files;
- copy scenario fixture directories into a clean worktree;
- inject candidate agent files with `--agent-candidate agent=file` without modifying repo agents;
- install a generated trace plugin for scripted subagent scenarios;
- record task, read-only tool-after-approval, and final-response trace events;
- validate scripted subagent output with exact equality;
- run `scenario` and `evaluate` commands with optional timeouts and JSON evaluation output;
- evaluate trace assertions into `score_inputs`, `trace_errors`, and assertion results suitable for a DSPy metric.

This is enough for the non-DSPy checkpoint: candidate prompts can be sandboxed, traced, and scored without adding a Python harness. The remaining work is to connect DSPy to these existing scenario/evaluate entrypoints and tighten repeatability controls as needed for optimization runs.

## Required `cli-v2` Additions

### 1. DSPy Harness Adapter

Build the external harness around the existing `evaluate` command:

```bash
cli-v2 evaluate \
  --scenario sandbox/scenarios/reviewer-overreach/scenario.json \
  --agent-candidate orchestrator=/tmp/candidate-orchestrator.md \
  --json
```

The harness should treat the JSON result as the prediction object. Important fields already available are:

```json
{
  "status": 0,
  "passed": true,
  "score_inputs": {
    "task_calls": [],
    "reviewer_prompts": [],
    "planner_prompts": [],
    "implementer_prompts": [],
    "readonly_tools_after_approval": [],
    "final_response": ""
  },
  "trace_errors": [],
  "assertions": []
}
```

### 2. Timeout And Repeatability Controls

DSPy may run many candidate trials. The CLI should make runs bounded and reproducible.

Already available:

- `--timeout-ms`
- `--json`
- explicit `--dest` for keeping or inspecting a sandbox

Still useful future additions:

- `--max-steps`
- `--seed`
- `--quiet`
- `--run-id`
- a first-class `--keep-sandbox` convenience flag when `--dest` is omitted

### 3. Scenario And Metric Expansion

Continue adding scenario fixtures and assertion types only when they expose behavior needed by DSPy scoring. Existing scenario files already cover multi-agent copying, fixture seeding, candidate replacement, trace recording, and assertion evaluation.

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
