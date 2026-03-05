# This script is part of a standard Python package layout.
# The nested structure (screenshot_sync/screenshot_sync/cli.py) is required by
# the `uv_build` backend to correctly identify the package name and isolate
# the installable code from project metadata like `pyproject.toml`.

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
        # We don't capture output so it streams to the terminal (manual)
        # or to the log files (launchd)
        subprocess.run(cmd, check=True, text=True)
    except subprocess.CalledProcessError as e:
        print(f"Sync failed with exit code {e.returncode}", file=sys.stderr)
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

def logs_launchd():
    """Tails the launchd logs."""
    out_log = Path.home() / f"Library/Logs/{PLIST_LABEL}.out.log"
    err_log = Path.home() / f"Library/Logs/{PLIST_LABEL}.err.log"
    
    print(f"Tailing logs for {PLIST_LABEL}...")
    print(f"Out: {out_log}")
    print(f"Err: {err_log}")
    print("-" * 40)
    
    try:
        subprocess.run(["tail", "-f", str(out_log), str(err_log)])
    except KeyboardInterrupt:
        print("\nStopped tailing logs.")

def main():
    parser = argparse.ArgumentParser(
        description=f"Sync screenshots to a remote VM (Config: {CONFIG_FILE})"
    )
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # Sync command
    subparsers.add_parser("sync", help="Execute the sync manually")

    # Launchd commands
    launchd_parser = subparsers.add_parser("launchd", help="Manage launchd agent")
    launchd_parser.add_argument("action", choices=["install", "uninstall", "status", "logs"], help="Action to perform")

    args = parser.parse_args()

    match args.command:
        case "sync":
            run_sync()
        case "launchd":
            match args.action:
                case "install":
                    install_launchd()
                case "uninstall":
                    uninstall_launchd()
                case "status":
                    status_launchd()
                case "logs":
                    logs_launchd()
        case _:
            parser.print_help()

if __name__ == "__main__":
    main()
