# screenshot

Canonical screenshot-domain CLI for dotfiles.

It owns:

- screenshot folder configuration
- filename matching rules
- clipboard history state
- sync configuration
- event handling for "copy newest screenshot path to clipboard"

## Install

```bash
uv tool install ./bin/screenshot --force --no-cache
```

## Test

```bash
uv run pytest
```

## CLI

```bash
screenshot --help
screenshot watch-path
screenshot clipboard on-event
screenshot clipboard list
screenshot clipboard copy --index 2
screenshot sync command
screenshot sync run
```

## Docs

- `bin/screenshot/docs/architecture.md`
