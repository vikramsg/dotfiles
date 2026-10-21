import copy
import importlib.util
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
