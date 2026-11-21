#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

import argparse
import json
import os
import subprocess
import sys


def run_json(*argv):
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(
            result.stderr.strip() or result.stdout.strip() or f"{argv[0]} failed"
        )
    return json.loads(result.stdout)


def post(path, body):
    return run_json("opencode", "api", "post", path, "--data", json.dumps(body))["data"]


def split():
    parent_id = os.environ.get("OPENCODE_SESSION_ID")
    terminal_id = os.environ.get("HC_TERMINAL_ID")
    if not parent_id or not terminal_id:
        raise RuntimeError("Run /split from an OpenCode session in a Herdr pane")

    terminal = run_json("hc", "get", terminal_id, "--json")
    labels = terminal.get("labels") or {}
    space_id, tab_id = labels.get("herdr.space"), labels.get("herdr.tab")
    if not space_id or not tab_id:
        raise RuntimeError(f"Herdr terminal {terminal_id} is not assigned to a tab")

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
    run_json(
        "hc",
        "run",
        "--json",
        "--bg",
        "--keep",
        "--no-parent",
        "--cwd",
        fork["location"]["directory"],
        "--label",
        f"herdr.space={space_id}",
        "--label",
        f"herdr.tab={tab_id}",
        "--",
        "opencode",
        "--session",
        fork_id,
    )
    print(
        "Herdr places the new pane to the right of the last pane in this tab, "
        "which may not be the calling pane."
    )


if __name__ == "__main__":
    argparse.ArgumentParser(
        description="Fork the current OpenCode session into a Herdr pane to the right."
    ).parse_args()
    try:
        split()
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        sys.exit(f"/split: {error}")
