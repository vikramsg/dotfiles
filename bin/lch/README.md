# lch

Thin watcher orchestrator for dotfiles jobs (`launchd` on macOS, `systemd --user` on Linux).

It owns:

- job ids and labels
- LaunchAgent plist generation (macOS)
- systemd user unit generation (Linux)
- install/uninstall/status/logs flows
- dispatch from native watcher into domain CLIs

## Install

```bash
uv tool install ./bin/lch --force --no-cache
```

## Test

```bash
uv run pytest
```

## CLI

```bash
lch --help
lch config
lch list
lch launchd list
lch launchd page --page 1 --page-size 25
lch install lch-screenshot-clipboard
lch install lch-screenshot-sync
lch status lch-screenshot-clipboard
lch status lch-screenshot-sync
lch logs lch-screenshot-clipboard
lch logs lch-screenshot-sync
lch run lch-screenshot-clipboard
lch run lch-screenshot-sync
lch uninstall lch-screenshot-clipboard
lch uninstall lch-screenshot-sync
```

## Docs

- `bin/lch/docs/architecture.md`
- `bin/lch/docs/screenshot-integration.md`

`lch config` reports the single effective config file path currently in use, the configured namespace, and the derived launchd paths.

The repo-managed config source of truth lives at `lch/config.json`. Use `just lch` to symlink it into `~/.config/lch/config.json` and install the tool.

On Linux sink machines, `just lch` installs the `lch-screenshot-clipboard` watcher job only.

`lch launchd list` uses an interactive pager when stdout is a TTY and renders the full discovered launchd dataset. Use `lch launchd page` for deterministic, non-interactive pagination in tests and scripts.
