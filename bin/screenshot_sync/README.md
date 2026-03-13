# Screenshot Sync

A native, event-driven screenshot synchronization tool for macOS that copies new screenshots to a remote Linux VM.

## Features

- **Event-Driven**: Uses macOS `launchd` (WatchPaths) to trigger syncs instantly when a file is added to your desktop.
- **Efficient**: Uses `rsync` over SSH to only transfer new files.
- **Safe**: Strictly copies files (no deletions) and filters only macOS screenshot patterns (`Screenshot *.png`, `Screen Shot *.png`).
- **Zero Overhead**: Does not run a persistent background process. macOS wakes the tool only when needed.
- **Configurable**: Config-driven via JSON and environment variables.

## Architecture

1.  **Triggers**: `launchd` monitors the `SCREENSHOT_DIR` (defaults to `~/Desktop`).
2.  **Tool**: `screenshot-sync` is a `uv`-managed Python tool.
3.  **Sync**: `rsync` performs the transfer using your local `~/.ssh/config` for credentials.
4.  **Logging**: Execution logs are stored in `~/Library/Logs/com.user.screenshotsync.{out,err}.log`.

## Installation

### 1. Configure SSH
Ensure your remote VM is defined in `~/.ssh/config` (so `rsync` can connect without a password):
```sshconfig
Host my-linux-vm
    HostName 1.2.3.4
    User youruser
    IdentityFile ~/.ssh/id_rsa
```

### 2. Configure the Tool
Create your configuration file at `~/.config/screenshot-sync/config.json`:
```json
{
  "vm_host": "my-linux-vm",
  "remote_dir": "~/Pictures/Screenshots/"
}
```

### 3. Install the Tool
Using `uv` from this repo:

```bash
uv tool install ./bin/screenshot_sync --force
```

Or directly from GitHub:

```bash
uv tool install "git+https://github.com/vikramsg/dotfiles.git#subdirectory=bin/screenshot_sync" --force
```

### 4. Enable the Sync Agent
Load the `launchd` service to start monitoring your desktop:
```bash
screenshot-sync launchd install
```

## Management Commands

| Command | Description |
| --- | --- |
| `screenshot-sync self-update` | Updates the tool from GitHub and restarts the agent. |
| `screenshot-sync launchd install` | Generates the plist and starts the `launchd` monitoring. |
| `screenshot-sync launchd status` | Checks if the sync agent is active. |
| `screenshot-sync launchd logs` | Tails the sync agent's logs. |
| `screenshot-sync launchd uninstall` | Stops and removes the `launchd` agent. |
| `screenshot-sync sync` | Manually triggers a synchronization. |

## Configuration Options

- **`vm_host`**: The SSH host alias from your `~/.ssh/config`.
- **`remote_dir`**: The destination directory on the remote Linux VM.
- **`SCREENSHOT_DIR`** (Env Var): Optional. Set this if you have changed your default macOS screenshot location from `~/Desktop`.

## Development & Testing

Tests are located in `bin/screenshot_sync/tests` and cover configuration parsing, command construction, and installation verification.

Run tests:
```bash
uv run pytest
```

Run from the package directory: `bin/screenshot_sync`.
