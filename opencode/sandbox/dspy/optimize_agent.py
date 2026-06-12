#!/usr/bin/env python3
"""DSPy-compatible optimizer harness for the orchestrator agent."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from metrics import ScenarioScore, aggregate_score, scenario_score  # type: ignore
    from scenarios import discover_scenarios, evaluate_candidate, repo_root  # type: ignore
else:
    from .metrics import ScenarioScore, aggregate_score, scenario_score
    from .scenarios import discover_scenarios, evaluate_candidate, repo_root

try:  # Optional by design: default local mode must remain stdlib-only.
    import dspy  # type: ignore  # noqa: F401
except ImportError:  # pragma: no cover - depends on optional environment.
    dspy = None


SMOKE_MARKER = "DSPY_SMOKE_IMPROVED"


@dataclass(frozen=True)
class Candidate:
    name: str
    markdown: str


@dataclass(frozen=True)
class CandidateResult:
    candidate: Candidate
    path: Path
    score: float
    scenario_scores: list[ScenarioScore]


def split_frontmatter(markdown: str) -> tuple[str, str]:
    """Preserve leading YAML frontmatter exactly and return body separately."""

    if not markdown.startswith("---\n"):
        return "", markdown

    marker = markdown.find("\n---\n", 4)
    if marker < 0:
        return "", markdown

    end = marker + len("\n---\n")
    return markdown[:end], markdown[end:]


def local_candidates(markdown: str, *, smoke: bool) -> list[Candidate]:
    """Generate deterministic candidate variants without model calls."""

    frontmatter, body = split_frontmatter(markdown)
    additions = [
        (
            "delegation-clarity",
            "\n\n## Optimization note\n\n- Re-check that planner, implementer, and reviewer context is complete before each delegation.\n",
        ),
        (
            "final-check-clarity",
            "\n\n## Optimization note\n\n- After reviewer approval, perform and mention a direct read-only final check before declaring success.\n",
        ),
    ]
    if smoke:
        additions.insert(
            0,
            (
                "smoke-improved",
                f"\n\n## Smoke optimization marker\n\n- {SMOKE_MARKER}: include the deterministic improvement marker.\n",
            ),
        )
    return [Candidate(name, frontmatter + body.rstrip() + addition) for name, addition in additions]


def build_local_optimizer(smoke: bool) -> Callable[[str], list[Candidate]]:
    return lambda markdown: local_candidates(markdown, smoke=smoke)


def build_dspy_optimizer(smoke: bool) -> Callable[[str], list[Candidate]]:
    if dspy is None:
        raise SystemExit("DSPy mode requires installing the dspy extra")
    # Keep the public shape DSPy-compatible while avoiding mandatory model calls.
    return build_local_optimizer(smoke)


def write_candidate(out_dir: Path, candidate: Candidate) -> Path:
    candidate_dir = out_dir / "candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    path = candidate_dir / f"{candidate.name}.md"
    path.write_text(candidate.markdown, encoding="utf-8")
    return path


def evaluate_markdown(
    *,
    candidate: Candidate,
    candidate_path: Path,
    scenarios: list[Path],
    root: Path,
    source_root: Path | None,
    timeout_ms: int | None,
    env: dict[str, str] | None,
) -> CandidateResult:
    scores: list[ScenarioScore] = []
    for scenario in scenarios:
        run = evaluate_candidate(
            scenario=scenario,
            candidate=candidate_path,
            root=root,
            source_root=source_root,
            timeout_ms=timeout_ms,
            env=env,
        )
        scores.append(scenario_score(scenario.name, run.evaluation))
    return CandidateResult(
        candidate=candidate,
        path=candidate_path,
        score=aggregate_score(scores),
        scenario_scores=scores,
    )


def create_smoke_fixture(root: Path) -> tuple[Path, Path, dict[str, str]]:
    """Create temporary source/scenario files plus fake opencode for smoke mode."""

    source = root / "source"
    scenario_dir = root / "scenario"
    bin_dir = root / "bin"
    (source / "agents").mkdir(parents=True)
    (scenario_dir / "worktree").mkdir(parents=True)
    bin_dir.mkdir()

    (source / "opencode.json").write_text(json.dumps({"plugin": []}, indent=2) + "\n", encoding="utf-8")
    (source / "agents" / "orchestrator.md").write_text("weak smoke orchestrator\n", encoding="utf-8")
    (source / "agents" / "planner.md").write_text("planner\n", encoding="utf-8")
    (scenario_dir / "request.md").write_text("Exercise deterministic DSPy smoke optimization.\n", encoding="utf-8")
    (scenario_dir / "expected.json").write_text(
        json.dumps(
            {
                "assertions": [
                    {
                        "name": "smoke_marker",
                        "type": "taskPromptIncludes",
                        "agent": "planner",
                        "required": [SMOKE_MARKER],
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    scenario = scenario_dir / "scenario.json"
    scenario.write_text(
        json.dumps(
            {
                "name": "dspy-smoke",
                "primaryAgent": "orchestrator",
                "config": "opencode.json",
                "agents": {"orchestrator": "agents/orchestrator.md", "planner": "agents/planner.md"},
                "promptFile": "request.md",
                "fixtureDir": "worktree",
                "expectedFile": "expected.json",
                "scriptedSubagents": {"planner": ["scripted planner output"]},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    fake_opencode = bin_dir / "opencode"
    fake_opencode.write_text(
        "#!/usr/bin/env node\n"
        "import { readFileSync, writeFileSync } from 'node:fs'\n"
        "import path from 'node:path'\n"
        "const args = process.argv.slice(2)\n"
        "const agent = args[args.indexOf('--agent') + 1]\n"
        "const agentFile = path.join(process.env.XDG_CONFIG_HOME, 'opencode', 'agents', agent + '.md')\n"
        "const prompt = readFileSync(agentFile, 'utf8')\n"
        "writeFileSync(process.env.OPENCODE_SANDBOX_TRACE_FILE, JSON.stringify({ type: 'task', agent: 'planner', prompt, output: 'scripted planner output' }) + '\\n')\n"
        "console.log('dspy smoke run')\n",
        encoding="utf-8",
    )
    fake_opencode.chmod(fake_opencode.stat().st_mode | stat.S_IXUSR)
    env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}
    return source, scenario, env


def result_to_json(result: CandidateResult) -> dict[str, object]:
    return {
        "name": result.candidate.name,
        "path": str(result.path),
        "score": result.score,
        "scenarios": [score.__dict__ for score in result.scenario_scores],
    }


def optimize(args: argparse.Namespace) -> dict[str, object]:
    root = repo_root()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    smoke_temp: tempfile.TemporaryDirectory[str] | None = None
    source_root: Path | None = None
    env: dict[str, str] | None = None
    try:
        if args.smoke:
            smoke_temp = tempfile.TemporaryDirectory(prefix="opencode-dspy-smoke-")
            source_root, scenario, env = create_smoke_fixture(Path(smoke_temp.name))
            scenarios = [scenario]
            agent_path = source_root / "agents" / "orchestrator.md"
        else:
            scenarios = discover_scenarios(args.scenario, root)
            agent_path = Path(args.agent).expanduser().resolve()

        baseline_markdown = agent_path.read_text(encoding="utf-8")
        baseline = Candidate("baseline", baseline_markdown)
        baseline_path = write_candidate(out_dir, baseline)
        baseline_result = evaluate_markdown(
            candidate=baseline,
            candidate_path=baseline_path,
            scenarios=scenarios,
            root=root,
            source_root=source_root,
            timeout_ms=args.timeout_ms,
            env=env,
        )

        optimizer = build_dspy_optimizer(args.smoke) if args.mode == "dspy" else build_local_optimizer(args.smoke)
        candidate_results = [baseline_result]
        for candidate in optimizer(baseline_markdown):
            candidate_path = write_candidate(out_dir, candidate)
            candidate_results.append(
                evaluate_markdown(
                    candidate=candidate,
                    candidate_path=candidate_path,
                    scenarios=scenarios,
                    root=root,
                    source_root=source_root,
                    timeout_ms=args.timeout_ms,
                    env=env,
                )
            )

        best = max(candidate_results, key=lambda result: result.score)
        optimized_path = out_dir / "optimized-orchestrator.md"
        optimized_path.write_text(best.candidate.markdown, encoding="utf-8")

        summary = {
            "mode": args.mode,
            "smoke": args.smoke,
            "baseline_score": baseline_result.score,
            "best_candidate": best.candidate.name,
            "best_score": best.score,
            "improved": best.score > baseline_result.score,
            "optimized_path": str(optimized_path),
            "candidates": [result_to_json(result) for result in candidate_results],
        }
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        if args.smoke and not summary["improved"]:
            raise SystemExit("smoke optimization did not improve over baseline")
        return summary
    finally:
        if smoke_temp is not None:
            smoke_temp.cleanup()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True, help="Directory for generated artifacts")
    parser.add_argument("--agent", default="opencode/agents/orchestrator.md", help="Baseline orchestrator markdown")
    parser.add_argument("--scenario", action="append", help="Scenario JSON file; may be repeated")
    parser.add_argument("--timeout-ms", type=int, help="Maximum opencode runtime per scenario")
    parser.add_argument("--json", action="store_true", help="Print summary JSON to stdout")
    parser.add_argument("--smoke", action="store_true", help="Run deterministic local smoke optimization")
    parser.add_argument("--mode", choices=("local", "dspy"), default="local", help="Optimizer mode")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    summary = optimize(args)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"best={summary['best_candidate']} score={summary['best_score']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
