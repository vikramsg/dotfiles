# screenshot config

This directory contains the repo-managed configuration for the `screenshot` tool.

## Source of truth

- repo file: `screenshot/config.json`
- live path: `~/.config/screenshot/config.json`

The live config should be a symlink back to this repo file.

## Setup

Run:

```bash
just screenshot
```

That command:

- creates `~/.config/screenshot`
- symlinks `screenshot/config.json` to `~/.config/screenshot/config.json`
- installs the `screenshot` CLI with `uv tool install ./bin/screenshot --force --no-cache`

For shell shortcuts, run `just zsh` to symlink `zsh/.zsh_screenshot` to `~/.zsh_screenshot`. That helper adds:

- `ss ls`
- `ss <index>`
- `ss cp <dest>`

## Format

```json
{
  "screenshot_dir": "~/Screenshots",
  "clipboard_history_limit": 5,
  "sync": {
    "vm_host": "my-vm",
    "remote_dir": "~/Pictures/Screenshots/"
  }
}
```

Use `screenshot config` to see the single effective config path currently in use.
