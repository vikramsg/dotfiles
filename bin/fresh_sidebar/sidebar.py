import fcntl
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys


PLUGIN_ID = "dotfiles.fresh-sidebar"
TOKEN = "dotfiles-fresh-sidebar"


class Herdr:
    def call(self, method, **params):
        with socket.socket(socket.AF_UNIX) as connection:
            connection.connect(os.environ["HERDR_SOCKET_PATH"])
            connection.sendall(
                (
                    json.dumps(
                        {"id": "fresh-sidebar", "method": method, "params": params}
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
            "label": "Fresh docking",
            "workspace_id": workspace_id,
        },
        focus=False,
    )


def open_sidebar(host, caller_id):
    panes = host.call("pane.list")["panes"]
    caller = next(pane for pane in panes if pane["pane_id"] == caller_id)
    tab_id = caller["tab_id"]
    for pane in panes:
        if pane["tab_id"] == tab_id and TOKEN in pane.get("tokens", {}):
            host.call("plugin.pane.focus", pane_id=pane["pane_id"])
            return pane["pane_id"]

    if shutil.which("fresh") is None:
        raise RuntimeError("Fresh is not installed; run just fresh")
    directory = caller.get("foreground_cwd") or caller["cwd"]
    tree = host.call("layout.export", tab_id=tab_id)["layout"]["root"]
    original_ids = pane_ids(tree)
    anchor = original_ids[0]

    # Herdr moves preserve live PTYs, unlike layout.apply. Holding each other
    # terminal in an unfocused tab lets us wrap the original tree at its root.
    # Each holding tab disappears when its terminal moves back.
    sidebar_id = None
    try:
        for pane_id in original_ids[1:]:
            hold_terminal(host, pane_id, caller["workspace_id"])
        sidebar = host.call(
            "plugin.pane.open",
            plugin_id=PLUGIN_ID,
            entrypoint="editor",
            target_pane_id=anchor,
            direction="right",
            cwd=directory,
            env={"FRESH_SIDEBAR_WAIT": "1", "FRESH_HERDR_SIDEBAR": "1"},
            focus=False,
        )
        sidebar_id = sidebar["plugin_pane"]["pane"]["pane_id"]
        host.call(
            "pane.report_metadata",
            pane_id=sidebar_id,
            source=TOKEN,
            tokens={TOKEN: "1"},
        )
        restore_split_tree(host, tree, tab_id)
        host.call("layout.set_split_ratio", tab_id=tab_id, path=[], ratio=0.6)
        host.call("pane.send_text", pane_id=sidebar_id, text="start\n")
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


def run_editor():
    host = Herdr()
    pane_id = os.environ["HERDR_PANE_ID"]
    if os.environ.get("FRESH_SIDEBAR_WAIT") == "1":
        if sys.stdin.readline().strip() != "start":
            return
    host.call(
        "pane.report_metadata", pane_id=pane_id, source=TOKEN, tokens={TOKEN: "1"}
    )
    try:
        subprocess.run(["fresh", "--no-restore"], check=False)
    finally:
        host.call("pane.close", pane_id=pane_id)


def main():
    if os.environ.get("HERDR_ENV") != "1":
        raise RuntimeError("Fresh sidebar must run inside Herdr")
    if sys.argv[1] == "run":
        run_editor()
        return
    state_directory = Path(os.environ["HERDR_PLUGIN_STATE_DIR"])
    state_directory.mkdir(parents=True, exist_ok=True)
    with (state_directory / "open.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        context = json.loads(os.environ["HERDR_PLUGIN_CONTEXT_JSON"])
        open_sidebar(Herdr(), context["focused_pane_id"])


if __name__ == "__main__":
    main()
