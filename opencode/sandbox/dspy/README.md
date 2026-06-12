# DSPy-compatible sandbox optimization harness

This directory contains a Python harness that evaluates orchestrator prompt
variants through the existing `cli-v2 evaluate --json` command. Generated
candidate files are written under `--out-dir`; the repo agent files are read as
baselines and are not overwritten by default.

## Deterministic smoke proof

```sh
python3 opencode/sandbox/dspy/optimize_agent.py --smoke --out-dir /tmp/opencode-dspy-smoke --json
```

Smoke mode creates a temporary fake `opencode` binary on `PATH`, but still calls
the real command:

```sh
npm --prefix opencode run sandbox:v2 -- evaluate --json
```

The baseline intentionally misses a required marker, while a deterministic local
candidate adds it. The summary should report `"improved": true`.

## Real scenario optimization

```sh
python3 opencode/sandbox/dspy/optimize_agent.py \
  --out-dir /tmp/opencode-dspy-real \
  --scenario opencode/sandbox/scenarios/passing-positive/scenario.json \
  --json
```

Omit `--scenario` to evaluate all built-in sandbox scenarios. Each candidate is
passed as `--agent-candidate orchestrator=<candidate.md>`.

## Outputs

- `candidates/*.md` - baseline and candidate markdown files.
- `optimized-orchestrator.md` - the best scored candidate for review.
- `summary.json` - baseline score, candidate scores, per-scenario scores, and
  whether the best candidate improved.

## Optional DSPy mode

Default `local` mode uses only the Python standard library. To experiment with
DSPy later, install the optional extra from `opencode/sandbox` and use
`--mode dspy`. The scenario/evaluate contract remains the same, and model/API
configuration can be layered on without changing generated artifacts.
