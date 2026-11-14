import copy
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

spec = importlib.util.spec_from_file_location(
    "sidebar", Path(__file__).parents[1] / "sidebar.py"
)
sidebar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sidebar)


def pane(pane_id):
    return {"type": "pane", "pane_id": pane_id}


def split(first, second, direction="right", ratio=0.5):
    return {
        "type": "split",
        "direction": direction,
        "ratio": ratio,
        "first": first,
        "second": second,
    }


def remove(tree, pane_id):
    if tree["type"] == "pane":
        return None if tree["pane_id"] == pane_id else tree
    first, second = remove(tree["first"], pane_id), remove(tree["second"], pane_id)
    if first is None:
        return second
    if second is None:
        return first
    return {**tree, "first": first, "second": second}


def insert(tree, target, new_pane, direction, ratio):
    if tree["type"] == "pane":
        return (
            split(tree, new_pane, direction, ratio)
            if tree["pane_id"] == target
            else tree
        )
    return {
        **tree,
        "first": insert(tree["first"], target, new_pane, direction, ratio),
        "second": insert(tree["second"], target, new_pane, direction, ratio),
    }


class FakeHerdr:
    def __init__(self, tree):
        self.tabs = {"t1": copy.deepcopy(tree), "t2": pane("other")}
        self.panes = {
            pane_id: {
                "pane_id": pane_id,
                "tab_id": "t1",
                "workspace_id": "w1",
                "cwd": "/spawn",
                "foreground_cwd": "/project with spaces",
            }
            for pane_id in sidebar.pane_ids(tree)
        }
        self.panes["other"] = {
            "pane_id": "other",
            "tab_id": "t2",
            "tokens": {sidebar.TOKEN: "1"},
        }
        self.focused = None
        self.launch_directory = None

    def call(self, method, **params):
        if method == "pane.list":
            return {"panes": list(self.panes.values())}
        if method == "plugin.list":
            return {
                "plugins": [
                    {"plugin_id": "persiyanov.reviewr", "plugin_root": "/plugins/reviewr"}
                ]
            }
        if method == "layout.export":
            return {"layout": {"root": copy.deepcopy(self.tabs[params["tab_id"]])}}
        if method == "plugin.pane.focus":
            self.focused = params["pane_id"]
        elif method == "pane.move":
            pane_id = params["pane_id"]
            old_tab = self.panes[pane_id]["tab_id"]
            self.tabs[old_tab] = remove(self.tabs[old_tab], pane_id)
            if self.tabs[old_tab] is None:
                del self.tabs[old_tab]
            destination = params["destination"]
            if destination["type"] == "new_tab":
                new_tab = f"holding-{pane_id}"
                self.tabs[new_tab] = pane(pane_id)
            else:
                new_tab = destination["tab_id"]
                self.tabs[new_tab] = insert(
                    self.tabs[new_tab],
                    destination["target_pane_id"],
                    pane(pane_id),
                    destination["split"],
                    destination.get("ratio", 0.5),
                )
            self.panes[pane_id]["tab_id"] = new_tab
        elif method == "plugin.pane.open":
            self.launch_directory = params["cwd"]
            self.pane_request = params
            self.tabs["t1"] = insert(
                self.tabs["t1"], params["target_pane_id"], pane("reviewr"), "right", 0.5
            )
            self.panes["reviewr"] = {"pane_id": "reviewr", "tab_id": "t1"}
            return {"plugin_pane": {"pane": {"pane_id": "reviewr"}}}
        elif method == "pane.report_metadata":
            self.panes[params["pane_id"]]["tokens"] = params["tokens"]
        elif method == "layout.set_split_ratio":
            self.tabs[params["tab_id"]]["ratio"] = params["ratio"]
        elif method == "pane.send_text":
            pass
        elif method == "pane.close":
            pane_id = params["pane_id"]
            tab_id = self.panes.pop(pane_id)["tab_id"]
            self.tabs[tab_id] = remove(self.tabs[tab_id], pane_id)
        else:
            raise AssertionError(method)
        return {}


class SidebarTests(unittest.TestCase):
    def test_docking_wraps_existing_tree_and_quit_restores_it(self):
        layouts = [
            pane("a"),
            split(pane("a"), pane("b"), ratio=0.7),
            split(pane("a"), pane("b"), "down", 0.4),
            split(
                split(pane("a"), pane("b"), "right", 0.3),
                split(pane("c"), pane("d"), "down", 0.6),
                "down",
                0.7,
            ),
        ]
        for tree in layouts:
            with self.subTest(tree=tree):
                host = FakeHerdr(tree)
                sidebar.toggle_sidebar(host, sidebar.pane_ids(tree)[-1])
                self.assertEqual(
                    host.tabs["t1"],
                    split(tree, pane("reviewr"), ratio=1 - sidebar.SIDEBAR_RATIO),
                )
                self.assertEqual(remove(host.tabs["t1"], "reviewr"), tree)
                self.assertEqual(set(host.tabs), {"t1", "t2"})
                self.assertEqual(host.tabs["t2"], pane("other"))
                self.assertEqual(host.launch_directory, "/project with spaces")

    def test_second_toggle_closes_only_the_callers_sidebar(self):
        tree = split(pane("a"), pane("b"), ratio=0.3)
        host = FakeHerdr(tree)
        sidebar.toggle_sidebar(host, "b")
        self.assertEqual(host.focused, "reviewr")
        self.assertIsNone(sidebar.toggle_sidebar(host, "a"))
        self.assertEqual(host.tabs["t1"], tree)
        self.assertEqual(host.tabs["t2"], pane("other"))

    def test_failed_reviewr_start_returns_live_terminals_from_holding_tabs(self):
        class FailedStart(FakeHerdr):
            def call(self, method, **params):
                if method == "pane.report_metadata":
                    super().call("pane.close", pane_id=params["pane_id"])
                    raise RuntimeError("reviewr exited during startup")
                return super().call(method, **params)

        tree = split(split(pane("a"), pane("b"), ratio=0.3), pane("c"), "down", 0.7)
        host = FailedStart(tree)
        with self.assertRaisesRegex(RuntimeError, "reviewr exited during startup"):
            sidebar.toggle_sidebar(host, "a")
        self.assertEqual(set(host.tabs), {"t1", "t2"})
        self.assertEqual(host.tabs["t1"], tree)

    def test_mid_reconstruction_failure_restores_original_ratios(self):
        class FailedMove(FakeHerdr):
            failed = False

            def call(self, method, **params):
                if (
                    method == "pane.move"
                    and params["pane_id"] == "b"
                    and params["destination"]["type"] == "tab"
                    and not self.failed
                ):
                    self.failed = True
                    raise RuntimeError("move interrupted")
                return super().call(method, **params)

        tree = split(split(pane("a"), pane("b"), ratio=0.3), pane("c"), "down", 0.7)
        host = FailedMove(tree)
        with self.assertRaisesRegex(RuntimeError, "move interrupted"):
            sidebar.toggle_sidebar(host, "a")
        self.assertEqual(host.tabs["t1"], tree)
        self.assertEqual(set(host.tabs), {"t1", "t2"})


def fake_program(directory, name, output, exit_code=0):
    """Write an executable that prints output and exits with exit_code."""
    output_file = Path(directory) / f"{name}.out"
    output_file.write_text(output)
    program = Path(directory) / name
    program.write_text(f'#!/bin/sh\ncat "{output_file}"\nexit {exit_code}\n')
    program.chmod(0o755)
    return program


class StackParentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name) / "repo"
        git = lambda *args, cwd=self.repo: subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True
        )
        self.repo.mkdir()
        git("init", "-q", "-b", "main")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "root")
        for name in ["a", "b", "c", "lone"]:
            git("branch", name)
        self.git = git

    def record_stacks(self, *stacks):
        """Write gh-stack's state file with stacks given as (trunk, [branch, ...])."""
        state = {
            "schemaVersion": 1,
            "stacks": [
                {"trunk": {"branch": trunk}, "branches": [{"branch": name} for name in names]}
                for trunk, names in stacks
            ],
        }
        (self.repo / ".git" / "gh-stack").write_text(json.dumps(state))

    def parent_on(self, branch, directory=None):
        self.git("switch", "-q", branch)
        return sidebar.stack_parent_branch(directory or self.repo)

    def test_parent_is_the_branch_below_the_current_one(self):
        self.record_stacks(("main", ["a", "b", "c"]))
        self.assertEqual(self.parent_on("c"), "b")

    def test_bottom_branch_uses_the_stack_trunk(self):
        self.record_stacks(("develop", ["a", "b"]))
        self.assertEqual(self.parent_on("a"), "develop")

    def test_the_stack_holding_the_branch_is_used(self):
        self.record_stacks(("main", ["lone"]), ("main", ["a", "b"]))
        self.assertEqual(self.parent_on("b"), "a")

    def test_branch_outside_every_stack_has_no_parent(self):
        self.record_stacks(("main", ["a", "b"]))
        self.assertIsNone(self.parent_on("lone"))

    def test_repository_without_stacks_has_no_parent(self):
        self.assertIsNone(self.parent_on("a"))

    def test_linked_worktree_reads_the_shared_state_file(self):
        self.record_stacks(("main", ["a", "b"]))
        worktree = self.repo.parent / "worktree"
        self.git("worktree", "add", "-q", str(worktree), "b")
        self.assertEqual(sidebar.stack_parent_branch(worktree), "a")

    def test_outside_a_git_checkout_there_is_no_parent(self):
        self.assertIsNone(sidebar.stack_parent_branch(self.repo.parent))


class StackToggleTests(unittest.TestCase):
    def setUp(self):
        self.bin_dir = tempfile.TemporaryDirectory()
        herdr = fake_program(self.bin_dir.name, "herdr", "/config/persiyanov.reviewr\n")
        env = {"HERDR_PLUGIN_ID": "dotfiles.herdr-sidebar", "HERDR_BIN_PATH": str(herdr)}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.bin_dir.cleanup)

    def test_stack_toggle_pins_reviewr_to_the_parent(self):
        tree = split(pane("a"), pane("b"))
        host = FakeHerdr(tree)
        sidebar.toggle_sidebar(host, "a", "stack", lambda directory: "feature/base")
        self.assertEqual(host.pane_request["entrypoint"], "reviewr-base")
        self.assertEqual(
            host.pane_request["env"],
            {
                "REVIEWR_BIN": "/plugins/reviewr/bin/herdr-reviewr",
                "REVIEWR_BASE": "feature/base",
                "REVIEWR_CONFIG_DIR": "/config/persiyanov.reviewr",
            },
        )
        self.assertEqual(
            host.tabs["t1"], split(tree, pane("reviewr"), ratio=1 - sidebar.SIDEBAR_RATIO)
        )

    def test_stack_toggle_outside_a_stack_opens_reviewrs_own_pane(self):
        host = FakeHerdr(pane("a"))
        sidebar.toggle_sidebar(host, "a", "stack", lambda directory: None)
        self.assertEqual(
            (host.pane_request["plugin_id"], host.pane_request["entrypoint"]),
            ("persiyanov.reviewr", "pane"),
        )

    def test_missing_reviewr_fails_before_the_layout_changes(self):
        class NoReviewr(FakeHerdr):
            def call(self, method, **params):
                if method == "plugin.list":
                    return {"plugins": []}
                return super().call(method, **params)

        tree = split(pane("a"), pane("b"))
        host = NoReviewr(tree)
        with self.assertRaisesRegex(RuntimeError, "persiyanov.reviewr is not installed"):
            sidebar.toggle_sidebar(host, "a", "stack", lambda directory: "feature/base")
        self.assertEqual(host.tabs["t1"], tree)


    def test_other_kind_replaces_the_sidebar_and_same_kind_closes_it(self):
        tree = split(pane("a"), pane("b"), "down", 0.7)
        docked = split(tree, pane("reviewr"), ratio=1 - sidebar.SIDEBAR_RATIO)
        host = FakeHerdr(tree)
        stack_base = lambda directory: "feature/base"

        sidebar.toggle_sidebar(host, "a", "plain")
        self.assertEqual(host.pane_request["entrypoint"], "pane")

        sidebar.toggle_sidebar(host, "a", "stack", stack_base)
        self.assertEqual(host.pane_request["env"]["REVIEWR_BASE"], "feature/base")
        self.assertEqual(host.panes["reviewr"]["tokens"], {sidebar.TOKEN: "stack"})
        self.assertEqual(host.tabs["t1"], docked)

        self.assertIsNone(sidebar.toggle_sidebar(host, "a", "stack", stack_base))
        self.assertEqual(host.tabs["t1"], tree)
        self.assertEqual(host.tabs["t2"], pane("other"))

    def test_swap_pressed_inside_the_sidebar_docks_beside_the_terminals(self):
        tree = split(pane("a"), pane("b"))
        host = FakeHerdr(tree)
        sidebar.toggle_sidebar(host, "a", "plain")
        sidebar.toggle_sidebar(host, "reviewr", "stack", lambda directory: "feature/base")
        self.assertEqual(host.pane_request["entrypoint"], "reviewr-base")
        self.assertEqual(
            host.tabs["t1"], split(tree, pane("reviewr"), ratio=1 - sidebar.SIDEBAR_RATIO)
        )


if __name__ == "__main__":
    unittest.main()
