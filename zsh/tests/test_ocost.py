"""Exercise the real zsh function with an executable fake OpenCode API."""

import json
import os
import copy
from datetime import datetime, time as midnight_time
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo


class OcostTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ocost-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.script = Path(__file__).resolve().parents[1] / ".zsh_script"
        self.environment = dict(os.environ, PATH=str(self.directory))
        self.response = self.directory / "response.json"
        self.projects_file = self.directory / "projects.json"
        self.project_usage_file = self.directory / "project-usage.json"
        self.calls = self.directory / "calls.txt"
        self.environment.update(
            OCOST_TEST_RESPONSE=str(self.response),
            OCOST_TEST_CALLS=str(self.calls),
            OCOST_TEST_EXIT="0",
            OCOST_TEST_PROJECTS=str(self.projects_file),
            OCOST_TEST_PROJECT_USAGE=str(self.project_usage_file),
        )
        self.executable = self.directory / "opencode2"
        self.executable.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "from urllib.parse import parse_qs, urlparse\n"
            "with open(os.environ['OCOST_TEST_CALLS'], 'a') as calls:\n"
            "    calls.write(' '.join(sys.argv[1:]) + '\\n')\n"
            "url = urlparse(sys.argv[3])\n"
            "query = parse_qs(url.query)\n"
            "if url.path == '/api/project':\n"
            "    response = Path(os.environ['OCOST_TEST_PROJECTS']).read_text()\n"
            "elif 'project' in query:\n"
            "    if os.environ.get('OCOST_TEST_FAIL_PROJECT'):\n"
            "        sys.exit(42)\n"
            "    payload = json.loads(Path(os.environ['OCOST_TEST_PROJECT_USAGE']).read_text())\n"
            "    response = json.dumps(payload[query['project'][0]])\n"
            "else:\n"
            "    response = Path(os.environ['OCOST_TEST_RESPONSE']).read_text()\n"
            "print(response)\n"
            "sys.exit(int(os.environ['OCOST_TEST_EXIT']))\n"
        )
        self.executable.chmod(0o755)
        jq = shutil.which("jq")
        if not jq:
            self.fail("jq must be installed to test ocost")
        (self.directory / "jq").symlink_to(jq)
        self.payload = {
            "data": {
                "cost": 15.125,
                "sessions": 7,
                "subagents": 2,
                "prompts": 25,
                "steps": 40,
                "tokens": {
                    "input": 100,
                    "output": 200,
                    "reasoning": 300,
                    "cache": {"read": 4000, "write": 500},
                },
                "models": [
                    {
                        "model": {
                            "providerID": "azure",
                            "id": "same-model",
                            "variant": "medium",
                        },
                        "cost": 2.125,
                    },
                    {
                        "model": {
                            "providerID": "azure",
                            "id": "same-model",
                            "variant": "high",
                        },
                        "cost": 10,
                    },
                    {"model": {"providerID": "other", "id": "same-model"}, "cost": 3},
                ],
                "extra": {"preserve": True},
            }
        }
        for model in self.payload["data"]["models"]:
            model.update(steps=10, tokens=copy.deepcopy(self.payload["data"]["tokens"]))
        self.response.write_text(json.dumps(self.payload))
        self.projects = [
            {"id": "project&one", "canonical": "/work/repo with spaces"},
            {"id": "project-two", "canonical": "/work/other"},
        ]
        self.project_usage = {
            project["id"]: copy.deepcopy(self.payload) for project in self.projects
        }
        self.project_usage["project&one"]["data"].update(
            cost=12.125,
            sessions=5,
            subagents=1,
            models=self.payload["data"]["models"][:2],
        )
        self.project_usage["project-two"]["data"].update(
            cost=3,
            sessions=2,
            subagents=1,
            models=self.payload["data"]["models"][2:],
        )
        self.projects_file.write_text(json.dumps(self.projects))
        self.project_usage_file.write_text(json.dumps(self.project_usage))

    def invoke(self, *arguments):
        return subprocess.run(
            [
                "/bin/zsh",
                "-f",
                "-c",
                'source "$1"; shift; ocost "$@"',
                "ocost-test",
                str(self.script),
                *arguments,
            ],
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_table_shows_projects_and_model_token_details(self):
        # GIVEN two projects and unsorted model rows with distinct providers/variants
        # WHEN the default command renders the response
        result = self.invoke()
        # THEN the API total is preserved and numeric descending sorting retains all rows
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("OpenCode V2 usage", result.stdout)
        self.assertRegex(result.stdout, r"Total cost\s+\$15\.125000")
        self.assertRegex(result.stdout, r"Root sessions\s+7")
        self.assertRegex(result.stdout, r"Subagents\s+2")
        self.assertRegex(result.stdout, r"Prompts\s+25")
        self.assertRegex(result.stdout, r"Assistant steps\s+40")
        self.assertIn("Project: /work/repo with spaces", result.stdout)
        self.assertIn("Project: /work/other", result.stdout)
        self.assertRegex(result.stdout, r"Input tokens\s+100")
        self.assertIn("Input: 100  Output: 200  Reasoning: 300", result.stdout)
        self.assertIn("Cache read: 4000  Cache write: 500", result.stdout)
        self.assertLess(
            result.stdout.index("Project: /work/repo with spaces"),
            result.stdout.index("Project: /work/other"),
        )
        rows = [
            line.split() for line in result.stdout.splitlines() if "same-model" in line
        ]
        self.assertEqual(
            rows,
            [
                ["azure", "same-model", "high", "10.000000", "10"],
                ["azure", "same-model", "medium", "2.125000", "10"],
                ["other", "same-model", "default", "3.000000", "10"],
            ],
        )
        calls = self.calls.read_text().splitlines()
        self.assertEqual(len(calls), 4)
        self.assertIn("project=project%26one", calls[2])
        self.assertNotIn("do not reconcile", result.stdout)

    def test_json_preserves_the_complete_api_response(self):
        # GIVEN a response including fields not used by the table
        # WHEN JSON output is requested
        result = self.invoke("--json")
        # THEN overall fields are preserved and every project response is included
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["data"], self.payload["data"])
        self.assertEqual(
            report["projects"],
            [
                {"project": project, "usage": self.project_usage[project["id"]]}
                for project in self.projects
            ],
        )

    def test_empty_usage_is_valid(self):
        # GIVEN a service with no usage
        self.payload["data"].update(
            cost=0, sessions=0, subagents=0, prompts=0, steps=0, models=[]
        )
        self.response.write_text(json.dumps(self.payload))
        self.projects_file.write_text("[]")
        # WHEN usage is shown
        result = self.invoke()
        # THEN a genuine zero is displayed successfully
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"Total cost\s+\$0\.000000")
        self.assertIn("No project usage in this window", result.stdout)

    def test_invalid_responses_never_print_a_usage_report(self):
        # GIVEN malformed JSON, an API error, or an unsupported statistics shape
        for response in [
            "",
            "{",
            "null",
            '{"error":"unavailable"}',
            '{"data":{}}',
            json.dumps(self.payload) + json.dumps(self.payload),
            json.dumps(self.payload).replace('"cost": 15.125', '"cost": "15.125"'),
            json.dumps(self.payload).replace('"models": [', '"models": [null,'),
        ]:
            for arguments in [(), ("--json",)]:
                with self.subTest(response=response, arguments=arguments):
                    self.response.write_text(response)
                    # WHEN either output mode is requested
                    result = self.invoke(*arguments)
                    # THEN the command fails instead of showing misleading totals
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")
                    self.assertIn(
                        "invalid OpenCode V2 statistics response", result.stderr
                    )

    def test_failed_api_request_does_not_render_its_stdout(self):
        # GIVEN an API process that produces output but exits unsuccessfully
        self.environment["OCOST_TEST_EXIT"] = "42"
        # WHEN usage is requested
        result = self.invoke()
        # THEN the failure is visible and stdout is not mistaken for a successful report
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("unable to fetch", result.stderr)

    def test_missing_dependencies_fail_before_calling_the_api(self):
        # GIVEN each required executable is absent in turn
        for dependency in ["jq", "opencode2"]:
            with self.subTest(dependency=dependency):
                executable = self.directory / dependency
                hidden = self.directory / (dependency + ".hidden")
                executable.rename(hidden)
                try:
                    # WHEN usage is requested
                    result = self.invoke()
                    # THEN the missing requirement is named and no API request is made
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")
                    self.assertIn(f"{dependency} is required", result.stderr)
                    self.assertFalse(self.calls.exists())
                finally:
                    hidden.rename(executable)

    def test_bad_arguments_do_not_call_the_api(self):
        # GIVEN unsupported arguments
        for arguments in [
            ("--unknown",),
            ("--json", "extra"),
            ("",),
            ("--days",),
            ("--days", "-1"),
            ("--days", "abc"),
            ("--days", "1.5"),
            ("--days", "99999999999999999999999"),
            ("--days", "1", "--days", "2"),
        ]:
            with self.subTest(arguments=arguments):
                # WHEN the function is invoked
                result = self.invoke(*arguments)
                # THEN usage is printed to stderr without an API request
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("usage: ocost", result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertFalse(self.calls.exists())

    def test_help_needs_no_dependencies_or_service(self):
        # GIVEN neither dependency is available
        self.environment["PATH"] = str(self.directory / "missing")
        # WHEN help is requested
        result = self.invoke("--help")
        # THEN help succeeds locally
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage: ocost", result.stdout)
        self.assertFalse(self.calls.exists())

    def test_days_range_is_shared_by_all_statistics_requests(self):
        # GIVEN a rolling seven-day window and either option order
        for arguments in [("--days", "7", "--json"), ("--json", "--days", "07")]:
            with self.subTest(arguments=arguments):
                self.calls.write_text("")
                before = time.time() * 1000
                # WHEN the detailed report is fetched
                result = self.invoke(*arguments)
                after = time.time() * 1000
                # THEN every stats request uses the same exact seven-day range
                self.assertEqual(result.returncode, 0, result.stderr)
                queries = [
                    parse_qs(urlparse(line.split(" ", 2)[2]).query)
                    for line in self.calls.read_text().splitlines()
                    if "/api/session/stats?" in line
                ]
                self.assertEqual(len(queries), 3)
                start = int(queries[0]["from"][0])
                end = int(queries[0]["to"][0])
                self.assertEqual(end - start, 7 * 86400000)
                self.assertGreaterEqual(end, before - 1)
                self.assertLessEqual(end, after + 1)
                for query in queries:
                    self.assertEqual(query["from"], [str(start)])
                    self.assertEqual(query["to"], [str(end)])

    def test_days_zero_starts_at_local_midnight(self):
        # GIVEN local timezones with different offsets and DST rules
        for timezone in ["UTC", "America/Los_Angeles", "Asia/Kolkata"]:
            with self.subTest(timezone=timezone):
                self.environment["TZ"] = timezone
                self.calls.write_text("")
                zone = ZoneInfo(timezone)
                before = datetime.now(zone).date()
                # WHEN zero days is requested
                result = self.invoke("--days", "0")
                after = datetime.now(zone).date()
                # THEN the lower bound is local midnight, not UTC or the current instant
                self.assertEqual(result.returncode, 0, result.stderr)
                url = self.calls.read_text().splitlines()[0].split(" ", 2)[2]
                start = int(parse_qs(urlparse(url).query)["from"][0])
                self.assertIn(
                    start,
                    [
                        int(
                            datetime.combine(date, midnight_time(), zone).timestamp()
                            * 1000
                        )
                        for date in [before, after]
                    ],
                )
                self.assertIn("Window: today (local midnight)", result.stdout)

    def test_all_time_has_no_recent_cutoff(self):
        # GIVEN no days argument
        # WHEN usage is fetched
        result = self.invoke()
        # THEN the API range includes all records, not just recently active sessions
        self.assertEqual(result.returncode, 0, result.stderr)
        url = self.calls.read_text().splitlines()[0].split(" ", 2)[2]
        self.assertEqual(parse_qs(urlparse(url).query)["from"], ["0"])
        self.assertIn("Window: all time", result.stdout)

    def test_project_request_failure_does_not_print_partial_totals(self):
        # GIVEN the overall request succeeds but a project request fails
        self.environment["OCOST_TEST_FAIL_PROJECT"] = "1"
        # WHEN the report is fetched
        result = self.invoke()
        # THEN no partial report is presented as complete
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("unable to fetch", result.stderr)
        self.assertIn("project=project%26one", result.stderr)

    def test_invalid_projects_fail_clearly(self):
        # GIVEN an invalid project response, including duplicate IDs
        for payload in ["null", "{}", "[{}]", json.dumps(self.projects * 2)]:
            with self.subTest(payload=payload):
                self.projects_file.write_text(payload)
                # WHEN the report is fetched
                result = self.invoke()
                # THEN invalid discovery cannot silently omit projects
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn("invalid OpenCode V2 projects response", result.stderr)

    def test_invalid_project_usage_fails_clearly(self):
        # GIVEN a project's cost is missing
        del self.project_usage["project-two"]["data"]["cost"]
        self.project_usage_file.write_text(json.dumps(self.project_usage))
        # WHEN the report is fetched
        result = self.invoke()
        # THEN it fails without printing otherwise-valid totals
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("invalid OpenCode V2 statistics response", result.stderr)
        self.assertIn("project=project-two", result.stderr)

    def test_different_projects_with_same_directory_remain_distinct(self):
        # GIVEN two project IDs share a directory, as can happen after migration
        self.projects[1]["canonical"] = self.projects[0]["canonical"]
        self.projects_file.write_text(json.dumps(self.projects))
        # WHEN the report is fetched
        result = self.invoke("--json")
        # THEN neither project's usage is lost or counted twice
        self.assertEqual(result.returncode, 0, result.stderr)
        projects = json.loads(result.stdout)["projects"]
        self.assertEqual(
            [row["project"]["id"] for row in projects], ["project&one", "project-two"]
        )
        self.assertEqual(sum(row["usage"]["data"]["cost"] for row in projects), 15.125)

    def test_project_total_discrepancy_is_disclosed(self):
        # GIVEN the service changes between the separate overall and project reads
        self.project_usage["project-two"]["data"]["cost"] = 4
        self.project_usage_file.write_text(json.dumps(self.project_usage))
        # WHEN the report is displayed
        result = self.invoke()
        # THEN it discloses the discrepancy instead of claiming a consistent snapshot
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("project costs do not reconcile", result.stdout)

    def test_zero_cost_usage_is_not_hidden(self):
        # GIVEN a model with recorded tokens/steps but no configured cost
        self.project_usage["project-two"]["data"]["models"][0]["cost"] = 0
        self.project_usage["project-two"]["data"]["cost"] = 0
        self.project_usage_file.write_text(json.dumps(self.project_usage))
        # WHEN the detailed report is displayed
        result = self.invoke()
        # THEN its project, model, and tokens remain visible despite zero cost
        self.assertEqual(result.returncode, 0, result.stderr)
        detail = result.stdout.split("Project: /work/other", 1)[1]
        self.assertRegex(detail, r"same-model\s+default\s+0\.000000\s+10")
        self.assertIn("Input: 100  Output: 200  Reasoning: 300", detail)


if __name__ == "__main__":
    unittest.main()
