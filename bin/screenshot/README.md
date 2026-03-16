# screenshot

Canonical screenshot-domain CLI for dotfiles.

It owns:

- screenshot folder configuration
- filename matching rules
- clipboard history state
- sync configuration
- event handling for "copy newest screenshot path to clipboard"

Clipboard and CLI path output use shell-safe `~`-relative paths such as `~/Screenshots/Screen\ Shot\ 2026-03-14\ at\ 10.11.00\ AM.png`.

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
screenshot config
screenshot watch-path
screenshot clipboard on-event
screenshot clipboard list
screenshot clipboard copy --index 2
screenshot sync command
screenshot sync run
```

`screenshot config` reports the single effective config file path, state file path, screenshot directory, and the expected JSON format.

The repo-managed config source of truth lives at `screenshot/config.json`. Use `just screenshot` to symlink it into `~/.config/screenshot/config.json` and install the tool.

`just zsh` also symlinks the zsh helper script `~/.zsh_screenshot`, which adds:

- `ss ls` -> `screenshot clipboard list`
- `ss <index>` -> `screenshot clipboard copy --index <index>`
- `ss cp <dest>` -> copy the current history item 1 file into `<dest>`

## Docs

- `bin/screenshot/docs/architecture.md`
- `screenshot/README.md`
