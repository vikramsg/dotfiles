"""Adapters for running existing sandbox scenarios from Python."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class EvaluationError(RuntimeError):
    """Raised when ``evaluate --json`` cannot produce parseable JSON."""


@dataclass(frozen=True)
class EvaluationRun:
    """Subprocess result plus parsed evaluation JSON."""

    scenario: Path
    returncode: int
    evaluation: dict[str, object]
    stderr: str


def repo_root() -> Path:
    """Resolve the repository root from this file location."""

    return Path(__file__).resolve().parents[3]


def default_scenarios(root: Path | None = None) -> list[Path]:
    """Return the built-in scenario files sorted for deterministic runs."""

    base = (root or repo_root()) / "opencode" / "sandbox" / "scenarios"
    return sorted(base.glob("*/scenario.json"))


def discover_scenarios(paths: list[str] | None, root: Path | None = None) -> list[Path]:
    """Resolve explicit scenario arguments or fall back to built-in scenarios."""

    if not paths:
        return default_scenarios(root)
    return [Path(path).expanduser().resolve() for path in paths]


def parse_evaluation_stdout(stdout: str) -> dict[str, object]:
    """Parse evaluation JSON from npm stdout.

    ``npm run`` may prefix stdout with lifecycle banners before the CLI's JSON.
    Prefer the whole stream, then fall back to scanning for a JSON object.
    """

    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, char in enumerate(stdout):
            if char != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(stdout[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and "assertions" in parsed and "status" in parsed:
                return parsed
        raise
    if not isinstance(parsed, dict):
        raise EvaluationError("evaluate JSON must be an object")
    return parsed


def evaluate_candidate(
    *,
    scenario: Path,
    candidate: Path,
    root: Path | None = None,
    source_root: Path | None = None,
    timeout_ms: int | None = None,
    env: Mapping[str, str] | None = None,
) -> EvaluationRun:
    """Run ``cli-v2 evaluate --json`` for one candidate and parse stdout JSON.

    The CLI intentionally exits with status 1 for failed assertions, so this
    function never uses ``check=True`` and treats parseable stdout as useful.
    """

    resolved_root = root or repo_root()
    command = [
        "npm",
        "--prefix",
        "opencode",
        "run",
        "sandbox:v2",
        "--",
        "evaluate",
        "--scenario",
        str(scenario),
        "--agent-candidate",
        f"orchestrator={candidate}",
        "--json",
    ]
    if source_root is not None:
        command.extend(["--orig", str(source_root)])
    if timeout_ms is not None:
        command.extend(["--timeout-ms", str(timeout_ms)])

    run_env = os.environ.copy()
    if env:
        run_env.update(env)

    completed = subprocess.run(
        command,
        cwd=resolved_root,
        env=run_env,
        text=True,
        capture_output=True,
        check=False,
    )

    try:
        evaluation = parse_evaluation_stdout(completed.stdout)
    except json.JSONDecodeError as error:
        raise EvaluationError(
            "evaluate did not return JSON; "
            f"rc={completed.returncode}; stderr={completed.stderr}"
        ) from error

    return EvaluationRun(
        scenario=scenario,
        returncode=completed.returncode,
        evaluation=evaluation,
        stderr=completed.stderr,
    )
