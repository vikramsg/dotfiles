import os
import pathlib
import subprocess
import tempfile
import unittest


SCRIPT = pathlib.Path(__file__).parents[1] / "hunk-review"


class HunkReviewLauncherTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tempdir.name)
        self.repo = root / "repo"
        self.repo.mkdir()
        subprocess.run(
            ["git", "init", "-b", "main"], cwd=self.repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.email", "hunk-review@test.invalid"],
            cwd=self.repo,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Hunk Review Test"], cwd=self.repo, check=True
        )
        (self.repo / "example.txt").write_text("one\n", encoding="utf8")
        subprocess.run(["git", "add", "example.txt"], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"], cwd=self.repo, check=True, capture_output=True
        )
        self.bin_dir = root / "bin"
        self.bin_dir.mkdir()
        self.capture = root / "hunk-invocation.txt"
        fake_hunk = self.bin_dir / "hunk"
        fake_hunk.write_text(
            "#!/bin/sh\n"
            "printf 'target=%s\\nargs=' \"${HUNK_REVIEW_TARGET:-}\" > \"$HUNK_CAPTURE\"\n"
            "printf '%s\\n' \"$*\" >> \"$HUNK_CAPTURE\"\n",
            encoding="utf8",
        )
        fake_hunk.chmod(0o755)

    def tearDown(self):
        self.tempdir.cleanup()

    def run_launcher(self):
        env = os.environ.copy()
        env["PATH"] = f"{self.bin_dir}{os.pathsep}{env['PATH']}"
        env["HUNK_CAPTURE"] = str(self.capture)
        return subprocess.run(
            [str(SCRIPT)],
            cwd=self.repo,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

    def invocation(self):
        return self.capture.read_text(encoding="utf8")

    def test_dirty_worktree_opens_working_tree_review(self):
        (self.repo / "example.txt").write_text("two\n", encoding="utf8")

        result = self.run_launcher()

        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.invocation(), "target=working\nargs=diff --mode stack\n")

    def test_clean_feature_branch_opens_main_comparison(self):
        subprocess.run(
            ["git", "switch", "-c", "feature"], cwd=self.repo, check=True, capture_output=True
        )
        (self.repo / "example.txt").write_text("two\n", encoding="utf8")
        subprocess.run(["git", "add", "example.txt"], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "feature"], cwd=self.repo, check=True, capture_output=True
        )

        result = self.run_launcher()

        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.invocation(), "target=main\nargs=diff main... --mode stack\n")

    def test_clean_main_without_changes_does_not_open_hunk(self):
        result = self.run_launcher()

        self.assertEqual(result.returncode, 0)
        self.assertFalse(self.capture.exists())
        self.assertIn("no changes", result.stdout)

    def test_directory_outside_git_reports_an_error(self):
        outside = pathlib.Path(self.tempdir.name) / "outside"
        outside.mkdir()
        env = os.environ.copy()
        env["PATH"] = f"{self.bin_dir}{os.pathsep}{env['PATH']}"
        env["HUNK_CAPTURE"] = str(self.capture)

        result = subprocess.run(
            [str(SCRIPT)],
            cwd=outside,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.capture.exists())
        self.assertIn("not inside a Git repository", result.stderr)


if __name__ == "__main__":
    unittest.main()
