#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

import argparse
import json
import os
import secrets
import subprocess
import sys

# The Herdr app's layout document in herdr-core. It is the app's own format,
# not a public API, so the script stops when its shape is not the one known.
DOC = "herdr-app"


def run_json(*argv):
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(
            result.stderr.strip() or result.stdout.strip() or f"{argv[0]} failed"
        )
    return json.loads(result.stdout)


def post(path, body):
    return run_json("opencode", "api", "post", path, "--data", json.dumps(body))["data"]


def rpc(method, params):
    """One JSON-RPC call through `hc connect`, after its hello."""
    calls = [
        {"jsonrpc": "2.0", "id": 0, "method": "hello", "params": {}},
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
    ]
    result = subprocess.run(
        ["hc", "connect"],
        input="".join(json.dumps(call) + "\n" for call in calls),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    for line in filter(str.strip, result.stdout.splitlines()):
        reply = json.loads(line)
        if reply.get("id") == 1:
            return reply
    raise RuntimeError(f"hc connect gave no reply to {method}: {result.stderr.strip()}")


def find_block(node, terminal_id, parent=None):
    """Returns the block showing terminal_id and its parent split."""
    if node.get("type") == "block":
        content = node.get("content") or {}
        return (node, parent) if content.get("terminal") == terminal_id else None
    for child in node.get("children") or []:
        found = find_block(child, terminal_id, node)
        if found:
            return found
    return None


def place_right(value, terminal_id, new_terminal_id):
    """Splits the block showing terminal_id, putting new_terminal_id to its right."""
    spaces = value.get("spaces") if isinstance(value, dict) else None
    if not isinstance(spaces, list):
        raise TypeError(
            f"the {DOC} document has a shape this script doesn't know; the app's format may have changed"
        )
    for space in spaces:
        for tab in space.get("tabs") or []:
            found = find_block(tab.get("root") or {}, terminal_id)
            if found:
                break
        else:
            continue
        break
    else:
        raise RuntimeError(f"Herdr terminal {terminal_id} has no pane in the app")

    block, parent = found
    new_block = {
        "id": "p" + secrets.token_hex(16),
        "type": "block",
        "content": {"terminal": new_terminal_id},
    }
    if parent.get("type") == "row":
        # Already side by side: the new pane takes half of the calling pane's width.
        if "size" in block:
            weight = block["size"]["weight"] / 2
            block["size"] = {"weight": weight}
            new_block["size"] = {"weight": weight}
        siblings = parent["children"]
        siblings.insert(siblings.index(block) + 1, new_block)
    else:
        # In a column: the calling pane becomes a row of itself and the new pane.
        row = {
            "id": "s" + secrets.token_hex(16),
            "type": "row",
            "children": [block, new_block],
        }
        if "size" in block:
            row["size"] = block.pop("size")
        siblings = parent["children"]
        siblings[siblings.index(block)] = row


def show_right_of(terminal_id, new_terminal_id):
    """Edits the app's layout, retrying when the app writes the document in between."""
    for _ in range(5):
        got = rpc("doc.get", {"name": DOC})
        if "error" in got:
            raise RuntimeError(f"doc.get {DOC}: {got['error']}")
        value, version = got["result"]["value"], got["result"]["version"]
        place_right(value, terminal_id, new_terminal_id)
        put = rpc("doc.set", {"name": DOC, "value": value, "version": version})
        if "result" in put:
            return
    raise RuntimeError(f"doc.set {DOC} kept losing to other writes: {put.get('error')}")


def split():
    parent_id = os.environ.get("OPENCODE_SESSION_ID")
    terminal_id = os.environ.get("HC_TERMINAL_ID")
    if not parent_id or not terminal_id:
        raise RuntimeError("Run /split from an OpenCode session in a Herdr pane")

    fork = post(f"/api/session/{parent_id}/fork", {})
    fork_id = fork["id"]
    print(f"Forked OpenCode session: {fork_id}", flush=True)

    # Submit this before the pane accepts the user's first instruction.
    post(
        f"/api/session/{fork_id}/prompt",
        {
            "text": f"You were forked from OpenCode session {parent_id}. Stop and wait for instructions."
        },
    )
    # Unlabelled, so the app does not place it after the tab's last pane;
    # the app labels it once the layout shows it.
    new_terminal_id = run_json(
        "hc",
        "run",
        "--json",
        "--bg",
        "--keep",
        "--no-parent",
        "--cwd",
        fork["location"]["directory"],
        "--",
        "opencode",
        "--session",
        fork_id,
    )["address"]
    try:
        show_right_of(terminal_id, new_terminal_id)
    except (
        RuntimeError,
        OSError,
        TypeError,
        ValueError,
        KeyError,
        subprocess.TimeoutExpired,
    ):
        for action in ("kill", "rm"):
            subprocess.run(
                ["hc", action, new_terminal_id], capture_output=True, check=False
            )
        raise


if __name__ == "__main__":
    argparse.ArgumentParser(
        description="Fork the current OpenCode session into a Herdr pane to the right."
    ).parse_args()
    try:
        split()
    except (
        RuntimeError,
        OSError,
        TypeError,
        ValueError,
        KeyError,
        subprocess.TimeoutExpired,
    ) as error:
        sys.exit(f"/split: {error}")
