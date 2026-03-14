# lch

Thin `launchd` orchestrator for dotfiles jobs.

It owns:

- job ids and labels
- LaunchAgent plist generation
- install/uninstall/status/logs flows
- dispatch from `launchd` into domain CLIs

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
lch install lch-screenshot-clipboard
lch status lch-screenshot-clipboard
lch logs lch-screenshot-clipboard
lch run lch-screenshot-clipboard
lch uninstall lch-screenshot-clipboard
```

## Docs

- `bin/lch/docs/architecture.md`
- `bin/lch/docs/screenshot-integration.md`
