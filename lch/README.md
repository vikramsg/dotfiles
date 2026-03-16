# lch config

This directory contains the repo-managed configuration for the `lch` tool.

## Source of truth

- repo file: `lch/config.json`
- live path: `~/.config/lch/config.json`

The live config should be a symlink back to this repo file.

## Setup

Run:

```bash
just lch
```

That command:

- creates `~/.config/lch`
- symlinks `lch/config.json` to `~/.config/lch/config.json`
- installs the `lch` CLI with `uv tool install ./bin/lch --force --no-cache`

## Format

```json
{
  "namespace": "com.vikramsg.dotfiles"
}
```

`namespace` is used to derive LaunchAgent labels such as `com.vikramsg.dotfiles.lch-screenshot-clipboard`.

Use `lch config` to see the single effective config path currently in use.
