#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

import argparse
import json
import os
import socket
import subprocess
import sys
from pathlib import Path


def run_json(*argv):
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(
            result.stderr.strip() or result.stdout.strip() or f"{argv[0]} failed"
        )
    return json.loads(result.stdout)


def herdr_app(request):
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    app_home = Path(os.environ.get("HERDR_APP_HOME") or config_home / "herdr-app")
    address = os.environ.get("HERDR_APP_SOCKET") or app_home / "herdr-app.sock"
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(10)
        try:
            client.connect(str(address))
        except OSError as error:
            raise RuntimeError(
                f"Cannot reach the Herdr window at {address}: {error}"
            ) from error
        client.sendall((json.dumps(request) + "\n").encode())
        with client.makefile("rb") as stream:
            reply = json.loads(stream.readline())
    if reply.get("error"):
        raise RuntimeError(f"Herdr: {reply['error']}")
    return reply


def find_pane(terminal_id, labels, world):
    # The desktop may prefix addresses and layout IDs with the VM's machine name.
    space_id, tab_id = labels.get("herdr.space"), labels.get("herdr.tab")
    matches = [
        terminal["pane"]
        for space in world["spaces"]
        if space["id"].rsplit("/", 1)[-1] == space_id
        for tab in space["tabs"]
        if tab["id"].rsplit("/", 1)[-1] == tab_id
        for terminal in tab["terminals"]
        if terminal["terminal"].rsplit("/", 1)[-1] == terminal_id
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"The Herdr window does not show a unique pane for terminal {terminal_id}"
        )
    return matches[0]


def post(path, body):
    return run_json("opencode", "api", "post", path, "--data", json.dumps(body))["data"]


def split():
    parent_id = os.environ.get("OPENCODE_SESSION_ID")
    terminal_id = os.environ.get("HC_TERMINAL_ID")
    if not parent_id or not terminal_id:
        raise RuntimeError("Run /split from an OpenCode session in a Herdr pane")

    terminal = run_json("hc", "get", terminal_id, "--json")
    pane = find_pane(terminal_id, terminal["labels"], herdr_app({"ls": True}))
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
    herdr_app(
        {
            "do": "pane.split",
            "args": {
                "pane": pane,
                "direction": "right",
                "argv": [
                    "opencode",
                    "--session",
                    fork_id,
                    fork["location"]["directory"],
                ],
            },
        }
    )


if __name__ == "__main__":
    argparse.ArgumentParser(
        description="Fork the current OpenCode session into a Herdr pane to the right."
    ).parse_args()
    try:
        split()
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        sys.exit(f"/split: {error}")
