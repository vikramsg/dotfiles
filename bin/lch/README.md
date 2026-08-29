# lch

Thin native orchestrator for path-triggered watchers and configured macOS services.

It owns:

- job ids and labels
- LaunchAgent plist generation (macOS)
- systemd user unit generation (Linux)
- install/uninstall/status/logs flows
- dispatch from native jobs into domain CLIs

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
lch install-watcher lch-example-watcher /path/to/watch /path/to/command arg
lch install lch-opener-tunnel
lch status lch-screenshot-clipboard
lch status lch-example-watcher
lch logs lch-screenshot-clipboard
lch logs lch-example-watcher
lch logs lch-example-watcher --follow
lch logs lch-example-watcher --paths
lch logs lch-opener-tunnel --follow
lch run lch-screenshot-clipboard
lch uninstall lch-screenshot-clipboard
lch uninstall lch-example-watcher
```

## Docs

- `bin/lch/docs/architecture.md`
- `bin/lch/docs/screenshot-integration.md`

`lch config` reports the single effective config file path currently in use, the configured namespace, and the derived launchd paths.

The repo-managed config source of truth lives at `lch/config.toml`. Use `just lch` to symlink it into `~/.config/lch/config.toml` and install the tool.

`install-watcher` accepts a job ID, watch path, and dispatch command. The native job stores that command directly; LCH does not rediscover domain configuration when an event occurs.

`lch list` combines configured jobs and services with installed namespace-owned LaunchAgents or systemd path units, deduplicated by job ID.

On Linux sink machines, `just lch` installs the `lch-screenshot-clipboard` watcher job only.

Persistent services are loaded from the TOML `services` table on macOS. Their
LaunchAgents use `RunAtLoad`, `KeepAlive`, and a restart throttle without
`WatchPaths`; dispatch replaces LCH with the configured domain command.

`lch launchd list` uses an interactive pager when stdout is a TTY and renders the full discovered launchd dataset. Use `lch launchd page` for deterministic, non-interactive pagination in tests and scripts.

`lch logs <job>` shows recent logs by default. Use `--follow` to stream new entries, `--lines <count>` to change the number of recent lines, `--stream stdout|stderr` on macOS to select a launchd stream, and `--paths` to print the underlying log files or journal commands.
