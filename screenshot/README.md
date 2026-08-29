# screenshot config

This directory contains the repo-managed configuration for the `screenshot` tool.

## Source of truth

- repo file: `screenshot/config.json`
- live path: `~/.config/screenshot/config.json`

The live config should be a symlink back to this repo file.

IMPORTANT: On macOS, this config is also the source of truth for the system screenshot save location. 
Running `just screenshot` applies `screenshot_dir` to `com.apple.screencapture` via `screenshot macos apply`.

## Setup

Run:

```bash
just screenshot
```

That command:

- creates `~/.config/screenshot`
- symlinks `screenshot/config.json` to `~/.config/screenshot/config.json`
- installs the `screenshot` CLI with `uv tool install ./bin/screenshot --force --no-cache`
- on macOS, creates the configured screenshot directory if needed and applies it to the system screenshot location

## Shared path setup

The workflow uses `/Users/Shared/Screenshots` on both hosts so a path dropped
from macOS also resolves on the VM. On Ubuntu, create the directory once with:

```bash
sudo install -d -o "$USER" -g "$(id -gn)" -m 700 /Users/Shared/Screenshots
```

Then run `just screenshot` on both hosts. 
On macOS this runs `screenshot macos apply`; on the VM it installs the same repo-managed configuration. 
After rsync copies a screenshot, OpenCode V2 on the VM can resolve the identical path as a native image attachment.

On Linux, directory watching/orchestration is owned by `lch`. On macOS, root setup derives `lch-screenshot-sync-<source-id>` jobs from this file and gives LCH each explicit watch path and dispatch command.

For shell shortcuts, run `just zsh` to symlink `zsh/.zsh_script` to `~/.zsh_script`. That helper adds:

- `ss ls`
- `ss <index>`
- `ss cp <dest>`
- `vm-tab`

## Format

```json
{
  "screenshot_dir": "/Users/Shared/Screenshots",
  "clipboard_history_limit": 5,
  "sync": {
    "sources": [
      {
        "id": "system",
        "local_dir": "/Users/Shared/Screenshots",
        "vm_host": "vm-us",
        "remote_dir": "/Users/Shared/Screenshots/",
        "include": ["Screenshot *.png", "Screen Shot *.png"]
      }
    ]
  }
}
```

Source IDs must be lowercase hyphenated slugs. Use `screenshot config` to see the effective config and `screenshot sync list` to list configured source IDs.

- macOS: `screenshot macos apply`

Clipboard writes are best-effort: `screenshot` will try `pbcopy`, `wl-copy`, or `xclip`. If none are available, it still updates screenshot history so `ss ls`, `ss <index>`, and `ss cp <dest>` continue to work.
