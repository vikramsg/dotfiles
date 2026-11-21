import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
JUSTFILE = REPO / "herdr-app/justfile"


class ProfileRecipesTest(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="herdr-profile-test-")
        self.addCleanup(self.scratch.cleanup)
        self.home = Path(self.scratch.name)
        self.main = self.home / ".config/herdr-app"
        (self.main / "layouts").mkdir(parents=True)
        (self.main / "mods/shipped").mkdir(parents=True)
        (self.main / "installed.json").write_text('{"shipped": {}}')
        (self.main / "layouts/main-copy.json").write_text(
            '{"blocks": [{"id": "app-sidebar", "content": {"address": "old"}}]}'
        )
        self.calls = self.home / "core-calls.jsonl"
        self.state = self.home / "machines.json"
        self.state.write_text(json.dumps({
            "default": [{"name": "vm-us", "target": "vm-us", "via": False}],
        }))
        self.bin = self.home / "bin"
        self.bin.mkdir()
        core = self.bin / "herdr-core"
        core.write_text(f"#!{sys.executable}\n" + """
import json, os, pathlib, sys
home = pathlib.Path(os.environ["HOME"])
session = os.environ.get("HC_SESSION", "default")
args = sys.argv[1:]
with (home / "core-calls.jsonl").open("a") as log:
    log.write(json.dumps([session, args]) + "\\n")
path = home / "machines.json"
state = json.loads(path.read_text())
machines = state.setdefault(session, [])
if args[:2] == ["machine", "ls"]:
    print(json.dumps({"machines": machines}))
elif args[:2] == ["machine", "add"]:
    machines.append({"name": args[args.index("--name") + 1], "target": args[2],
                     "session": args[args.index("--session") + 1], "via": False})
elif args[:2] == ["machine", "rm"]:
    state[session] = [m for m in machines if m["name"] != args[2]]
else:
    raise SystemExit("Unexpected core command: " + repr(args))
path.write_text(json.dumps(state))
""")
        core.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.home),
                        PATH=f"{self.bin}:{os.environ['PATH']}",
                        HC_SESSION="unrelated")

    def run_recipe(self, *args, success=True):
        result = subprocess.run(
            ["just", "-f", str(JUSTFILE), *args], env=self.env,
            text=True, capture_output=True,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def profile_home(self, name="work"):
        return self.home / f".config/herdr-app-{name}"

    def test_local_setup_copies_layout_and_links_settings_without_core_calls(self):
        self.run_recipe("profile", "work", "--local")
        profile = self.profile_home()
        self.assertEqual((profile / "settings.json").resolve(),
                         REPO / "herdr-app/settings.json")
        layout = json.loads((profile / "layouts/main-copy.json").read_text())
        self.assertEqual(layout["blocks"][0]["content"], {"mod": "app-sidebar"})
        self.assertTrue(layout["blocks"][0]["hidden"])
        self.assertFalse(self.calls.exists())

    def test_default_setup_registers_profile_session_and_local_refresh_keeps_it(self):
        self.run_recipe("profile", "work")
        state = json.loads(self.state.read_text())
        self.assertEqual(state["work"][0]["session"], "work")
        self.assertNotIn("unrelated", state)
        before = self.calls.read_text()
        self.run_recipe("profile", "work", "--local")
        self.assertEqual(self.calls.read_text(), before)
        self.assertEqual(json.loads(self.state.read_text()), state)

    def test_explicit_bulk_refresh_adds_machines_to_local_profiles(self):
        self.run_recipe("profile", "one", "--local")
        self.run_recipe("profile", "two", "--local")
        self.run_recipe("profiles")
        state = json.loads(self.state.read_text())
        for name in ("one", "two"):
            self.assertEqual(state[name][0]["session"], name)

    def test_invalid_arguments_have_no_setup_side_effects(self):
        for args in (("profile", "../escape"), ("profile", "work", "--unknown"),
                     ("profile", '$(touch "$HOME/injected")'),
                     ("profile", "work", '$(touch "$HOME/injected")')):
            with self.subTest(args=args):
                self.run_recipe(*args, success=False)
        self.assertFalse(self.profile_home().exists())
        self.assertFalse((self.home / "injected").exists())
        self.assertFalse(self.calls.exists())

    def test_removal_preserves_link_targets_other_profiles_and_core_state(self):
        self.run_recipe("profile", "work", "--local")
        self.run_recipe("profile", "other", "--local")
        target = self.home / "shared-settings.json"
        target.write_text("{}")
        (self.profile_home() / "extra.json").symlink_to(target)
        before = self.state.read_text()
        self.run_recipe("remove-profile", "work")
        self.assertFalse(self.profile_home().exists())
        self.assertTrue(self.profile_home("other").is_dir())
        self.assertTrue((self.main / "layouts/main-copy.json").is_file())
        self.assertEqual(target.read_text(), "{}")
        self.assertEqual(self.state.read_text(), before)
        self.assertFalse(self.calls.exists())

    def test_removal_rejects_unsafe_names_and_missing_profiles(self):
        for name in ("../herdr-app", "", '$(touch "$HOME/injected")', "missing"):
            with self.subTest(name=name):
                self.run_recipe("remove-profile", name, success=False)
        self.assertTrue(self.main.is_dir())
        self.assertFalse((self.home / "injected").exists())

    def test_removal_aborts_when_database_names_are_present(self):
        self.run_recipe("profile", "work", "--local")
        # Directories exercise the name guard without creating database files.
        for suffix in (".sqlite", ".db"):
            with self.subTest(suffix=suffix):
                database = self.profile_home() / f"state{suffix}"
                database.mkdir()
                self.run_recipe("remove-profile", "work", success=False)
                self.assertTrue(database.is_dir())
                self.assertTrue((self.profile_home() / "shared.json").is_file())
                database.rmdir()


if __name__ == "__main__":
    unittest.main()
