# screenshot config

This directory contains the repo-managed configuration for the `screenshot` tool.

## Source of truth

- repo file: `screenshot/config.json`
- live path: `~/.config/screenshot/config.json`

The live config should be a symlink back to this repo file.

On macOS, this config is also the source of truth for the system screenshot save location. Running `just screenshot` applies `screenshot_dir` to `com.apple.screencapture` via `screenshot macos apply`.

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

On Linux, directory watching/orchestration is owned by `lch`. Run `just lch` to install the sink watcher job (`lch-screenshot-clipboard`) that dispatches `screenshot clipboard on-event`.

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

Clipboard writes are best-effort: `screenshot` will try `pbcopy`, `wl-copy`, or `xclip`. If none are available, it still updates screenshot history so `ss ls`, `ss <index>`, and `ss cp <dest>` continue to work.
