import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


HERDR_DIRECTORY = Path(__file__).resolve().parents[1]


class HerdrSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)
        self.config = self.directory / "config"
        self.config.mkdir()
        for filename in ("justfile", "sidebar-settings.json", "sidebar-editor.txt"):
            shutil.copyfile(HERDR_DIRECTORY / filename, self.config / filename)
        self.calls = self.directory / "calls.jsonl"
        self.installed = self.directory / "installed.json"
        self.installed.write_text(json.dumps({"result": {"plugins": []}}))
        binary_directory = self.directory / "bin"
        binary_directory.mkdir()
        herdr = binary_directory / "herdr"
        herdr.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, pathlib, sys\n"
            "if sys.argv[1:] == ['plugin', 'list', '--json']:\n"
            "    print(pathlib.Path(os.environ['TEST_INSTALLED']).read_text())\n"
            "else:\n"
            "    with open(os.environ['TEST_CALLS'], 'a') as calls:\n"
            "        calls.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        )
        herdr.chmod(0o755)
        self.environment = {
            **os.environ,
            "PATH": f"{binary_directory}:{os.environ['PATH']}",
            "HOME": str(self.directory / "home"),
            "XDG_STATE_HOME": str(self.directory / "state"),
            "TEST_INSTALLED": str(self.installed),
            "TEST_CALLS": str(self.calls),
        }

    def run_recipe(self, recipe="install"):
        return subprocess.run(
            ["just", "--justfile", str(self.config / "justfile"), recipe],
            env=self.environment,
            text=True,
            capture_output=True,
            check=True,
        )

    def declare_plugins(self, plugins):
        (self.config / "plugins.json").write_text(json.dumps({"plugins": plugins}))

    def test_installed_subdirectory_plugin_is_skipped_but_sibling_is_installed(self):
        self.declare_plugins(
            [
                {"id": "first", "source": "owner/repo/plugins/first"},
                {
                    "id": "second",
                    "source": "owner/repo/plugins/second",
                    "ref": "v1.2.3",
                },
            ]
        )
        self.installed.write_text(
            json.dumps(
                {
                    "result": {
                        "plugins": [
                            {
                                "plugin_id": "first",
                                "source": {
                                    "kind": "github",
                                    "owner": "owner",
                                    "repo": "repo",
                                },
                            }
                        ]
                    }
                }
            )
        )
        self.run_recipe()
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual(
            calls,
            [
                [
                    "plugin",
                    "install",
                    "owner/repo/plugins/second",
                    "--ref",
                    "v1.2.3",
                    "-y",
                ]
            ],
        )

    def test_missing_unpinned_plugin_is_installed(self):
        self.declare_plugins([{"id": "first", "source": "owner/repo"}])
        self.run_recipe()
        self.assertEqual(
            json.loads(self.calls.read_text()),
            ["plugin", "install", "owner/repo", "-y"],
        )

    def test_settings_are_reapplied_without_losing_other_preferences(self):
        self.declare_plugins([])
        state_directory = (
            Path(self.environment["XDG_STATE_HOME"]) / "herdr/plugins/herdr-sidebar"
        )
        state_directory.mkdir(parents=True)
        state_file = state_directory / "state.json"
        state_file.write_text(
            json.dumps(
                {
                    "auto_open": True,
                    "dock_right": False,
                    "custom_editor_on_click": False,
                    "sidebar_width": 44,
                }
            )
        )
        self.run_recipe()
        self.run_recipe()
        self.assertEqual(
            json.loads(state_file.read_text()),
            {
                "auto_open": False,
                "dock_right": True,
                "custom_editor_on_click": True,
                "sidebar_width": 44,
            },
        )
        self.assertEqual(
            (state_directory / "editor-command.txt").read_text().strip(), "nvim"
        )

    def test_first_setup_uses_home_when_xdg_state_home_is_unset(self):
        self.environment.pop("XDG_STATE_HOME")
        self.run_recipe("configure-sidebar")
        state_directory = (
            Path(self.environment["HOME"]) / ".local/state/herdr/plugins/herdr-sidebar"
        )
        self.assertTrue(
            json.loads((state_directory / "state.json").read_text())["dock_right"]
        )
        self.assertEqual(
            (state_directory / "editor-command.txt").read_text().strip(), "nvim"
        )


if __name__ == "__main__":
    unittest.main()
