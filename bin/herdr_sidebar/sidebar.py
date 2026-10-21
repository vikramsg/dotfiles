"""Toggle reviewr as a full-height sidebar on the right of the current Herdr tab.

Herdr has no API that splits a tab at its root, so this composes public Herdr
socket APIs instead; README.md walks through the sequence. Moves keep the live
PTYs, whereas `layout.apply` would restart them.
"""

import fcntl
import json
import os
import socket
import sys
from pathlib import Path

TOKEN = "dotfiles-herdr-sidebar"
SIDEBAR_RATIO = 0.4


class Herdr:
    def call(self, method, **params):
        with socket.socket(socket.AF_UNIX) as connection:
            connection.connect(os.environ["HERDR_SOCKET_PATH"])
            connection.sendall(
                (
                    json.dumps(
                        {"id": "herdr-sidebar", "method": method, "params": params}
                    )
                    + "\n"
                ).encode()
            )
            response = json.loads(connection.makefile().readline())
        if "error" in response:
            raise RuntimeError(f"{method}: {response['error']['message']}")
        return response["result"]


def pane_ids(tree):
    if tree["type"] == "pane":
        return [tree["pane_id"]]
    return pane_ids(tree["first"]) + pane_ids(tree["second"])


def restore_split_tree(host, tree, tab_id):
    if tree["type"] == "pane":
        return
    host.call(
        "pane.move",
        pane_id=pane_ids(tree["second"])[0],
        destination={
            "type": "tab",
            "tab_id": tab_id,
            "target_pane_id": pane_ids(tree["first"])[0],
            "split": tree["direction"],
            "ratio": tree["ratio"],
        },
        focus=False,
    )
    restore_split_tree(host, tree["first"], tab_id)
    restore_split_tree(host, tree["second"], tab_id)


def hold_terminal(host, pane_id, workspace_id):
    host.call(
        "pane.move",
        pane_id=pane_id,
        destination={
            "type": "new_tab",
            "label": "sidebar docking",
            "workspace_id": workspace_id,
        },
        focus=False,
    )


def toggle_sidebar(host, caller_id):
    """Close the caller tab's sidebar if it has one, otherwise dock a new one.

    Returns the new sidebar's pane id, or None when the sidebar was closed.
    Closing needs no layout work: Herdr gives the closed column's width back
    to the untouched tree on the left.
    """
    panes = host.call("pane.list")["panes"]
    caller = next(pane for pane in panes if pane["pane_id"] == caller_id)
    tab_id = caller["tab_id"]
    for pane in panes:
        if pane["tab_id"] == tab_id and TOKEN in pane.get("tokens", {}):
            host.call("pane.close", pane_id=pane["pane_id"])
            return None

    directory = caller.get("foreground_cwd") or caller["cwd"]
    tree = host.call("layout.export", tab_id=tab_id)["layout"]["root"]
    original_ids = pane_ids(tree)
    anchor = original_ids[0]

    sidebar_id = None
    try:
        for pane_id in original_ids[1:]:
            hold_terminal(host, pane_id, caller["workspace_id"])
        sidebar = host.call(
            "plugin.pane.open",
            # Reviewr's own pane entrypoint, so reviewr's plugin keeps owning
            # its binary path and config.
            plugin_id="persiyanov.reviewr",
            entrypoint="pane",
            target_pane_id=anchor,
            direction="right",
            cwd=directory,
            focus=False,
        )
        sidebar_id = sidebar["plugin_pane"]["pane"]["pane_id"]
        # The token is how the next toggle finds this tab's sidebar.
        host.call(
            "pane.report_metadata",
            pane_id=sidebar_id,
            source=TOKEN,
            tokens={TOKEN: "1"},
        )
        restore_split_tree(host, tree, tab_id)
        host.call(
            "layout.set_split_ratio", tab_id=tab_id, path=[], ratio=1 - SIDEBAR_RATIO
        )
        host.call("plugin.pane.focus", pane_id=sidebar_id)
        return sidebar_id
    except Exception:
        # Rebuild from the exported tree even if failure occurred halfway
        # through reconstruction, preserving both live terminals and ratios.
        current = {pane["pane_id"]: pane for pane in host.call("pane.list")["panes"]}
        if sidebar_id in current:
            host.call("pane.close", pane_id=sidebar_id)
        for pane_id in original_ids[1:]:
            if current[pane_id]["tab_id"] == tab_id:
                hold_terminal(host, pane_id, caller["workspace_id"])
        restore_split_tree(host, tree, tab_id)
        raise


def main():
    if os.environ.get("HERDR_ENV") != "1":
        raise RuntimeError("herdr sidebar must run inside Herdr")
    if sys.argv[1] != "toggle":
        raise RuntimeError(f"unknown command {sys.argv[1]!r}")
    state_directory = Path(os.environ["HERDR_PLUGIN_STATE_DIR"])
    state_directory.mkdir(parents=True, exist_ok=True)
    # Two quick key presses must not dock twice or interleave pane moves.
    with (state_directory / "toggle.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        context = json.loads(os.environ["HERDR_PLUGIN_CONTEXT_JSON"])
        toggle_sidebar(Herdr(), context["focused_pane_id"])


if __name__ == "__main__":
    main()
