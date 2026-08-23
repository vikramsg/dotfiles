# lch config

This directory contains the repo-managed configuration for the `lch` tool.

## Source of truth

- repo file: `lch/config.toml`
- live path: `~/.config/lch/config.toml`

The live config should be a symlink back to this repo file.

## Setup

Run:

```bash
just lch
```

That command:

- creates `~/.config/lch`
- symlinks `lch/config.toml` to `~/.config/lch/config.toml`
- installs the `lch` CLI with `uv tool install ./bin/lch --force --no-cache`
- on Linux sink machines, installs `lch-screenshot-clipboard` so new files in the screenshot directory dispatch `screenshot clipboard on-event`

## Format

```toml
# Prefix used for native service labels.
namespace = "com.vikramsg.dotfiles"

[services.lch-opener-tunnel]
# Domain command run as a persistent macOS LaunchAgent.
command = ["opener-tunnel", "run"]
```

`namespace` is used to derive watcher labels such as `com.vikramsg.dotfiles.lch-screenshot-clipboard`.
The optional `services` table defines persistent macOS services; existing
screenshot watchers remain owned by LCH's watcher registry.

Use `lch config` to see the single effective config path currently in use.
