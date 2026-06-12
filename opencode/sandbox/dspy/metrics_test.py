from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from metrics import aggregate_score, scenario_score, score_evaluation
from optimize_agent import SMOKE_MARKER, local_candidates, split_frontmatter
from scenarios import evaluate_candidate, parse_evaluation_stdout


class MetricsTest(unittest.TestCase):
    def test_assertion_pass_ratio_scores_failed_json_without_returncode(self) -> None:
        evaluation = {
            "passed": False,
            "status": 0,
            "trace_errors": [],
            "assertions": [{"name": "a", "passed": True}, {"name": "b", "passed": False}],
        }

        self.assertEqual(score_evaluation(evaluation), 0.5)

    def test_safety_failures_hard_zero(self) -> None:
        for evaluation in [
            {"passed": False, "status": 0, "timed_out": True, "trace_errors": [], "assertions": []},
            {"passed": False, "status": 2, "trace_errors": [], "assertions": [{"passed": True}]},
            {"passed": False, "status": 0, "trace_errors": ["bad"], "assertions": [{"passed": True}]},
        ]:
            with self.subTest(evaluation=evaluation):
                self.assertEqual(score_evaluation(evaluation), 0.0)

    def test_aggregate_score_averages_scenarios(self) -> None:
        first = scenario_score("one", {"passed": True, "status": 0, "trace_errors": [], "assertions": []})
        second = scenario_score(
            "two",
            {
                "passed": False,
                "status": 0,
                "trace_errors": [],
                "assertions": [{"name": "a", "passed": True}, {"name": "b", "passed": False}],
            },
        )

        self.assertEqual(aggregate_score([first, second]), 0.75)
        self.assertEqual(second.failure_reason, "failed_assertions=b")


class AdapterTest(unittest.TestCase):
    def test_parse_evaluation_stdout_skips_npm_banner(self) -> None:
        parsed = parse_evaluation_stdout(
            "\n> sandbox:v2\n> npm run build:sandbox --silent && node sandbox/dist/cli-v2.js\n\n"
            + json.dumps({"passed": True, "status": 0, "trace_errors": [], "assertions": []})
            + "\n"
        )

        self.assertTrue(parsed["passed"])

    def test_evaluate_candidate_parses_json_when_subprocess_returns_one(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout=json.dumps(
                {
                    "passed": False,
                    "status": 0,
                    "trace_errors": [],
                    "assertions": [{"name": "a", "passed": False}],
                }
            ),
            stderr="assertion failed",
        )
        with patch("scenarios.subprocess.run", return_value=completed) as run:
            parsed = evaluate_candidate(
                scenario=Path("/tmp/scenario.json"),
                candidate=Path("/tmp/candidate.md"),
                root=Path("/repo"),
            )

        self.assertEqual(parsed.returncode, 1)
        self.assertFalse(parsed.evaluation["passed"])
        command = run.call_args.args[0]
        self.assertEqual(command[:7], ["npm", "--prefix", "opencode", "run", "sandbox:v2", "--", "evaluate"])
        self.assertIn("--json", command)


class OptimizerTest(unittest.TestCase):
    def test_frontmatter_is_preserved_exactly(self) -> None:
        markdown = "---\ndescription: test\n---\n# Body\n"

        frontmatter, body = split_frontmatter(markdown)
        candidate = local_candidates(markdown, smoke=True)[0]

        self.assertEqual(frontmatter, "---\ndescription: test\n---\n")
        self.assertEqual(body, "# Body\n")
        self.assertTrue(candidate.markdown.startswith(frontmatter + "# Body"))
        self.assertIn(SMOKE_MARKER, candidate.markdown)

    def test_generated_candidates_do_not_modify_baseline_file(self) -> None:
        with TemporaryDirectory() as tmp:
            baseline = Path(tmp) / "orchestrator.md"
            baseline.write_text("---\nmode: primary\n---\nweak\n", encoding="utf-8")

            _ = local_candidates(baseline.read_text(encoding="utf-8"), smoke=True)

            self.assertEqual(baseline.read_text(encoding="utf-8"), "---\nmode: primary\n---\nweak\n")


if __name__ == "__main__":
    unittest.main()
