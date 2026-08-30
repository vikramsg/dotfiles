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
- on macOS, enumerates `screenshot/config.json` sources and installs explicit LCH watchers
- on Linux sink machines, installs `lch-screenshot-clipboard` so new files in the screenshot directory dispatch `screenshot clipboard on-event`

## Format

```toml
# Prefix used for native service labels.
namespace = "com.vikramsg.dotfiles"

[services.lch-opener-tunnel]
# Command services replace `lch run` with the configured foreground command and
# inherit launchd lifecycle and stdout/stderr directly.
command = ["opener-tunnel", "run"]

# macOS application services launch through LaunchServices to preserve the
# signed bundle's TCC identity. LCH waits for the app, routes stdout/stderr to
# its normal service logs, and terminates the app when the service stops.
[services.lch-macflow.application]
type = "macos"
path = "~/Applications/Macflow.app"
```

`namespace` is used to derive watcher labels such as `com.vikramsg.dotfiles.lch-screenshot-clipboard`.
The optional `services` table accepts either a foreground `command` or an
`application`. Application definitions use a platform discriminator. The
`macos` type is supported; the reserved `linux` type is parsed but launching it
is not yet implemented. Domain-specific watcher definitions are supplied to LCH
by setup orchestration.

Use `lch config` to see the single effective config path currently in use.
