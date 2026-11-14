"""Toggle reviewr as a full-height sidebar on the right of the current Herdr tab.

Herdr has no API that splits a tab at its root, so this composes public Herdr
socket APIs instead; README.md walks through the sequence. Moves keep the live
PTYs, whereas `layout.apply` would restart them.
"""

import fcntl
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

TOKEN = "dotfiles-herdr-sidebar"
SIDEBAR_RATIO = 0.4
REVIEWR_PLUGIN_ID = "persiyanov.reviewr"

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


def run(command, **kwargs):
    """subprocess.run with a readable error when the program is not installed."""
    try:
        return subprocess.run(command, capture_output=True, text=True, **kwargs)
    except FileNotFoundError:
        raise RuntimeError(f"{command[0]} is not installed or not on PATH") from None


def stack_parent_branch(directory):
    """Return the gh stack parent of the branch checked out in directory, or None.

    The parent is the nearest unmerged branch below the current one, or the
    stack's trunk when every branch below is merged: a merged branch's commits
    are already in the trunk. `gh stack view` exits non-zero outside a stack,
    which means "no parent"; a missing gh is an error, not "no stack".
    """
    result = run(["gh", "stack", "view", "--json"], cwd=directory)
    if result.returncode != 0:
        return None
    stack = json.loads(result.stdout)
    names = [branch["name"] for branch in stack["branches"]]
    if stack["currentBranch"] not in names:
        return None
    below = stack["branches"][: names.index(stack["currentBranch"])]
    unmerged = [branch["name"] for branch in below if not branch["isMerged"]]
    return unmerged[-1] if unmerged else stack["trunk"]


def reviewr_pane_request(host, base):
    """plugin.pane.open parameters for reviewr, pinned to base when given.

    Reviewr's own `pane` entrypoint takes no arguments, so a pinned base runs
    reviewr's binary through this plugin's `reviewr-base` entrypoint instead.
    Herdr sets HERDR_PLUGIN_ID and HERDR_PLUGIN_CONFIG_DIR to this plugin's
    for that pane and ignores overrides in env, so the entrypoint's command
    re-exports them from REVIEWR_CONFIG_DIR before starting reviewr; otherwise
    reviewr would not read its own config.toml.
    """
    if base is None:
        return {"plugin_id": REVIEWR_PLUGIN_ID, "entrypoint": "pane"}
    reviewr = next(
        (plugin for plugin in host.call("plugin.list")["plugins"] if plugin["plugin_id"] == REVIEWR_PLUGIN_ID),
        None,
    )
    if reviewr is None:
        raise RuntimeError(f"{REVIEWR_PLUGIN_ID} is not installed")
    config_dir = run(
        [os.environ["HERDR_BIN_PATH"], "plugin", "config-dir", REVIEWR_PLUGIN_ID], check=True
    ).stdout.strip()
    return {
        "plugin_id": os.environ["HERDR_PLUGIN_ID"],
        "entrypoint": "reviewr-base",
        "env": {
            # Reviewr installs its binary at bin/herdr-reviewr under its plugin root.
            "REVIEWR_BIN": str(Path(reviewr["plugin_root"]) / "bin" / "herdr-reviewr"),
            "REVIEWR_BASE": base,
            "REVIEWR_CONFIG_DIR": config_dir,
        },
    }


def toggle_sidebar(host, caller_id, base_for=None):
    """Close the caller tab's sidebar if it has one, otherwise dock a new one.

    base_for(directory) returns the ref a new sidebar's branch scope should
    diff against, or None for reviewr's own base.

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
    base = base_for(directory) if base_for else None
    pane_request = reviewr_pane_request(host, base)
    tree = host.call("layout.export", tab_id=tab_id)["layout"]["root"]
    original_ids = pane_ids(tree)
    anchor = original_ids[0]

    sidebar_id = None
    try:
        for pane_id in original_ids[1:]:
            hold_terminal(host, pane_id, caller["workspace_id"])
        sidebar = host.call(
            "plugin.pane.open",
            **pane_request,
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
    base_for = {"toggle": None, "toggle-stack": stack_parent_branch}
    if sys.argv[1] not in base_for:
        raise RuntimeError(f"unknown command {sys.argv[1]!r}")
    state_directory = Path(os.environ["HERDR_PLUGIN_STATE_DIR"])
    state_directory.mkdir(parents=True, exist_ok=True)
    # Two quick key presses must not dock twice or interleave pane moves.
    with (state_directory / "toggle.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        context = json.loads(os.environ["HERDR_PLUGIN_CONTEXT_JSON"])
        toggle_sidebar(Herdr(), context["focused_pane_id"], base_for[sys.argv[1]])


if __name__ == "__main__":
    main()
