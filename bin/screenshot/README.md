# screenshot

Canonical screenshot-domain CLI for dotfiles.

It owns:

- screenshot folder configuration
- macOS screenshot location application from config
- filename matching rules
- clipboard history state
- sync configuration
- event handling for "copy newest screenshot path to clipboard"

Clipboard and CLI path output use shell-safe paths such as `/Users/Shared/Screenshots/Screen\ Shot\ 2026-03-14\ at\ 10.11.00\ AM.png`.

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
screenshot macos apply
screenshot watch-path
screenshot clipboard on-event
screenshot clipboard list
screenshot clipboard copy --index 2
screenshot sync list
screenshot sync command <source-id>
screenshot sync run <source-id>
screenshot sync watch-path <source-id>
```

`screenshot config` reports the single effective config file path, state file path, screenshot directory, and the expected JSON format.

On macOS, `screenshot macos apply` creates the configured screenshot directory if needed, writes the configured `screenshot_dir` into `com.apple.screencapture`, and restarts `SystemUIServer` so future screenshots land in the config-managed directory.

The repo-managed config source of truth lives at `screenshot/config.json`. Use `just screenshot` to symlink it into `~/.config/screenshot/config.json`, install the tool, and on macOS apply the configured screenshot location to the OS.

`just zsh` also symlinks the zsh helper script `~/.zsh_script`, which adds:

- `ss ls` -> `screenshot clipboard list`
- `ss <index>` -> `screenshot clipboard copy --index <index>`
- `ss cp <dest>` -> copy the current history item 1 file into `<dest>`
- `vm-tab` -> pick an existing remote tmux session with `fzf`, rename the current Ghostty tab, and attach via `autossh`

Sync sources are configured in `screenshot/config.json`. Each source owns its stable lowercase slug ID, local directory, matching rules, VM host, and remote destination; the CLI does not hard-code source paths or filename filters. `screenshot sync list` prints the configured source IDs for orchestrators such as LCH.

## Docs

- `bin/screenshot/docs/architecture.md`
- `screenshot/README.md`
