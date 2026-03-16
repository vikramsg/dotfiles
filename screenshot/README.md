# screenshot config

This directory contains the repo-managed configuration for the `screenshot` tool.

## Source of truth

- repo file: `screenshot/config.json`
- live path: `~/.config/screenshot/config.json`

The live config should be a symlink back to this repo file.

On macOS, this config is also the source of truth for the system screenshot save location. Running `just screenshot` applies `screenshot_dir` to `com.apple.screencapture` via `screenshot macos apply`.

On Linux, running `just screenshot` writes and enables a user systemd watcher (`screenshot-clipboard.path` + `screenshot-clipboard.service`) so new files in `screenshot_dir` automatically trigger `screenshot clipboard on-event`.

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
- on Linux, creates the configured screenshot directory if needed and enables user systemd units that watch it for new files

For shell shortcuts, run `just zsh` to symlink `zsh/.zsh_screenshot` to `~/.zsh_screenshot`. That helper adds:

- `ss ls`
- `ss <index>`
- `ss cp <dest>`

## Format

```json
{
  "screenshot_dir": "~/Desktop/Screenshots",
  "clipboard_history_limit": 5,
  "sync": {
    "vm_host": "dev-vm-vikram.europe-west3-b.orbio-development",
    "remote_dir": "~/Desktop/Screenshots/"
  }
}
```

Use `screenshot config` to see the effective config.

- macOS: `screenshot macos apply`
- Linux: `screenshot systemd apply`

Clipboard writes are best-effort: `screenshot` will try `pbcopy`, `wl-copy`, or `xclip`. If none are available, it still updates screenshot history so `ss ls`, `ss <index>`, and `ss cp <dest>` continue to work.
