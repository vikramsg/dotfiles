"""Metrics for scoring sandbox ``evaluate --json`` output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


JsonObject = Mapping[str, Any]


@dataclass(frozen=True)
class ScenarioScore:
    """Score and review notes for one evaluated scenario."""

    scenario: str
    score: float
    failure_reason: str | None = None


def score_evaluation(evaluation: JsonObject) -> float:
    """Return a deterministic score for one ``cli-v2 evaluate`` JSON object."""

    if evaluation.get("timed_out") is True:
        return 0.0
    if evaluation.get("status") != 0:
        return 0.0
    if evaluation.get("trace_errors"):
        return 0.0

    assertions = evaluation.get("assertions") or []
    if not assertions:
        return 1.0 if evaluation.get("passed") is True else 0.0

    if not isinstance(assertions, Sequence):
        return 0.0

    passed = sum(
        1
        for assertion in assertions
        if isinstance(assertion, Mapping) and assertion.get("passed") is True
    )
    return passed / len(assertions)


def failure_reason(evaluation: JsonObject) -> str | None:
    """Summarize why an evaluation did not receive a perfect score."""

    if evaluation.get("timed_out") is True:
        return "timed_out"
    if evaluation.get("status") != 0:
        return f"status={evaluation.get('status')}"
    trace_errors = evaluation.get("trace_errors") or []
    if trace_errors:
        return "trace_errors"

    assertions = evaluation.get("assertions") or []
    if isinstance(assertions, Sequence):
        failed = [
            assertion.get("name", "unnamed")
            for assertion in assertions
            if isinstance(assertion, Mapping) and assertion.get("passed") is not True
        ]
        if failed:
            return "failed_assertions=" + ",".join(str(name) for name in failed)

    if evaluation.get("passed") is not True:
        return "not_passed"
    return None


def scenario_score(scenario: str, evaluation: JsonObject) -> ScenarioScore:
    """Build a reviewable scenario score record."""

    return ScenarioScore(
        scenario=scenario,
        score=score_evaluation(evaluation),
        failure_reason=failure_reason(evaluation),
    )


def aggregate_score(scores: Iterable[ScenarioScore]) -> float:
    """Average scenario scores, returning zero for an empty scenario set."""

    values = [score.score for score in scores]
    if not values:
        return 0.0
    return sum(values) / len(values)
