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
        print(f"Error: Tool not found at {tool_path}. Please install it first using uv.", file=sys.stderr)
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
        
        # Show last 5 lines of logs
        out_log = Path.home() / f"Library/Logs/{PLIST_LABEL}.out.log"
        err_log = Path.home() / f"Library/Logs/{PLIST_LABEL}.err.log"
        
        if out_log.exists():
            print("\n--- Recent Output Logs ---")
            subprocess.run(["tail", "-n", "5", str(out_log)])
            
        if err_log.exists():
            print("\n--- Recent Error Logs ---")
            subprocess.run(["tail", "-n", "5", str(err_log)])
    else:
        print(f"Agent '{PLIST_LABEL}' is NOT loaded.")

def help_launchd():
    """Displays help for the launchd management commands."""
    print("This command manages the screenshot-sync launchd agent.")
    print("It runs via the 'screenshot-sync' tool installed via uv.")
    print()
    print("Allowed actions: install, uninstall, status, logs, debug, help")
    print()
    print("Investigation helpers:")
    print("  uv tool list               List installed tools")
    print("  uv tool list --show-paths  Show tool installation paths")
    print("  uv tool dir                Show uv tools directory")

def debug_launchd():
    """Runs uv tool commands to debug the installation."""
    print("=== UV Tool Debug Information ===")
    
    print("Tool directory:", flush=True)
    subprocess.run(["uv", "tool", "dir"])
    
    print("\nInstalled tool details:", flush=True)
    subprocess.run(["uv", "tool", "list", "--show-paths"])
    
    print("\n=== System Paths ===")
    print(f"Home: {Path.home()}")
    print(f"PATH: {os.environ.get('PATH')}")
    
    print("\n=== Plist Details ===")
    print(f"Label: {PLIST_LABEL}")
    print(f"Path:  {PLIST_PATH}")
    if PLIST_PATH.exists():
        print("Status: FILE EXISTS")
        print("\n--- Plist Content ---")
        print(PLIST_PATH.read_text())
    else:
        print("Status: FILE MISSING")

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

def config_help():
    """Displays help for the configuration file."""
    print(f"Screenshot Sync Configuration Help")
    print(f"====================================")
    print(f"Config Directory: {CONFIG_DIR}")
    print(f"Config File:      {CONFIG_FILE}")
    print()
    print("Expected JSON format:")
    print(json.dumps({
        "vm_host": "my-linux-vm",
        "remote_dir": "~/Pictures/Screenshots/"
    }, indent=2))
    print()
    print("Fields:")
    print("  vm_host:    The SSH host alias from your ~/.ssh/config")
    print("  remote_dir: The destination directory on the remote Linux VM")
    print()
    print("Environment Variables (Optional):")
    print("  SCREENSHOT_DIR: Path to watch for screenshots (Default: ~/Desktop)")

def self_update():
    """Updates the tool via uv tool upgrade."""
    print("Updating screenshot-sync via uv...")
    try:
        subprocess.run(["uv", "tool", "upgrade", "screenshot-sync"], check=True)
        print("\nUpdate completed successfully!")
        
        # Check if launchd agent is active and reload it
        result = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
        if PLIST_LABEL in result.stdout:
            print(f"Launchd agent '{PLIST_LABEL}' is currently active.")
            print("Reloading agent to apply the update...")
            subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
            subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=True)
            print("Agent reloaded successfully.")
        
    except subprocess.CalledProcessError as e:
        print(f"Failed to update screenshot-sync (exit code {e.returncode}).", file=sys.stderr)
        print("Ensure 'uv' is installed and accessible in your PATH.", file=sys.stderr)
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        description=f"Sync screenshots to a remote VM (Config: {CONFIG_FILE})"
    )
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # Sync command
    subparsers.add_parser("sync", help="Execute the sync manually")

    # Config help command
    subparsers.add_parser("config-help", help="Show configuration details and example")

    # Launchd commands
    launchd_parser = subparsers.add_parser("launchd", help="Manage launchd agent")
    launchd_parser.add_argument("action", choices=["install", "uninstall", "status", "logs", "debug", "help"], help="Action to perform")

    # Self-update command
    subparsers.add_parser("self-update", help="Update this tool to the latest version via uv")

    args = parser.parse_args()

    match args.command:
        case "sync":
            run_sync()
        case "config-help":
            config_help()
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
                case "debug":
                    debug_launchd()
                case "help":
                    help_launchd()
        case "self-update":
            self_update()
        case _:
            parser.print_help()

if __name__ == "__main__":
    main()
