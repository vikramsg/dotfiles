#!/usr/bin/env -S uv run --python 3.14t
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "python-dotenv",
# ]
# ///

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Configuration Label
PLIST_LABEL = "com.user.screenshotsync"
PLIST_PATH = Path.home() / "Library/LaunchAgents" / f"{PLIST_LABEL}.plist"
CONFIG_DIR = Path.home() / ".config/screenshot-sync"
CONFIG_FILE = CONFIG_DIR / "config.json"

@dataclass
class SyncConfig:
    vm_host: str
    remote_dir: str
    screenshot_dir: Path = field(
        default_factory=lambda: Path(os.getenv("SCREENSHOT_DIR", Path.home() / "Desktop"))
    )

    @classmethod
    def load(cls):
        if not CONFIG_FILE.exists():
            print(f"Error: Config file not found at {CONFIG_FILE}", file=sys.stderr)
            sys.exit(1)
        
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
        
        return cls(
            vm_host=data["vm_host"],
            remote_dir=data["remote_dir"]
        )

def run_sync():
    """Executes the rsync command to sync screenshots."""
    config = SyncConfig.load()
    
    # Absolute paths are required for launchd contexts
    local_dir = config.screenshot_dir.resolve()
    
    # rsync command construction
    # --include="Screenshot *.png" and --include="Screen Shot *.png"
    # --exclude="*" ensures we only sync matching files
    cmd = [
        "rsync",
        "-avz",
        "--include=Screenshot *.png",
        "--include=Screen Shot *.png",
        "--exclude=*",
        f"{local_dir}/",
        f"{config.vm_host}:{config.remote_dir}"
    ]
    
    try:
        # Run silently, but log errors to stderr if any
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        print(f"Sync failed: {e.stderr}", file=sys.stderr)
        sys.exit(1)

def install_launchd():
    """Generates and loads the launchd plist."""
    config = SyncConfig.load()
    local_dir = config.screenshot_dir.resolve()
    tool_path = Path.home() / ".local/bin/screenshot-sync"
    
    if not tool_path.exists():
        print(f"Error: Tool not found at {tool_path}. Please install it first with 'uv tool install --script {Path(__file__).resolve()}'", file=sys.stderr)
        sys.exit(1)

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{tool_path}</string>
        <string>sync</string>
    </array>
    <key>WatchPaths</key>
    <array>
        <string>{local_dir}</string>
    </array>
    <key>StandardErrorPath</key>
    <string>{Path.home()}/Library/Logs/{PLIST_LABEL}.err.log</string>
    <key>StandardOutPath</key>
    <string>{Path.home()}/Library/Logs/{PLIST_LABEL}.out.log</string>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
"""
    
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PLIST_PATH, "w") as f:
        f.write(plist_content)
    
    # Load the agent
    subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
    subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=True)
    print(f"Launchd agent installed and loaded: {PLIST_PATH}")

def uninstall_launchd():
    """Unloads and removes the launchd plist."""
    if PLIST_PATH.exists():
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
        PLIST_PATH.unlink()
        print(f"Launchd agent uninstalled: {PLIST_PATH}")
    else:
        print("Launchd agent not found.")

def status_launchd():
    """Checks the status of the launchd agent."""
    result = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    if PLIST_LABEL in result.stdout:
        print(f"Agent '{PLIST_LABEL}' is ACTIVE.")
        # Try to get more info
        info = subprocess.run(["launchctl", "list", PLIST_LABEL], capture_output=True, text=True)
        print(info.stdout)
    else:
        print(f"Agent '{PLIST_LABEL}' is NOT loaded.")

def main():
    parser = argparse.ArgumentParser(description="Sync screenshots to a remote VM.")
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # Sync command
    subparsers.add_parser("sync", help="Execute the sync manually")

    # Launchd commands
    launchd_parser = subparsers.add_parser("launchd", help="Manage launchd agent")
    launchd_parser.add_argument("action", choices=["install", "uninstall", "status"], help="Action to perform")

    args = parser.parse_args()

    if args.command == "sync":
        run_sync()
    elif args.command == "launchd":
        if args.action == "install":
            install_launchd()
        elif args.action == "uninstall":
            uninstall_launchd()
        elif args.action == "status":
            status_launchd()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
