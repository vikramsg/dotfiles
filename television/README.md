# Television

This directory contains repo-managed Television channel definitions.

The actual live Television config is not edited directly under `~/.config`. Instead, this repo stays the source of truth and the config is symlinked into place.

## Setup Model

- Channels live in `television/cable/` in this repo.
- `just television` creates the symlink from `~/.config/television/cable` to `television/cable`.
- `just all` also includes the `television` setup step.
- Tool dependencies are handled through the repo `Brewfile`, not by ad hoc manual installs.

## Dependencies

- `television` is installed through `Brewfile`.
- Channel-specific tools should also be declared through `Brewfile` when they are part of the expected setup.
- Current examples in this repo:
  - `lsof` is used by the `opencode` channel and is expected to exist as a normal system tool on macOS/Linux.
  - `mcat` is used by the `screenshots` channel and is installed through Homebrew.

Use:

```sh
just brew
just television
```

## Channels

- `tv opencode` shows running `opencode` instances and the working directory each one was started from.
- `tv screenshots` shows recent screenshots from the repo-managed screenshot directory.

## Known Shortcomings

### Image preview inside Television is limited

Television preview commands are rendered back into the TUI preview pane as terminal text output. That means terminal graphics protocols like Kitty, Sixel, and iTerm image output do not survive reliably inside the preview pane.

In practice:

- `mcat`, `imgcat`, Kitty graphics, and similar tools may work directly in a terminal or tmux pane, but not inside the Television preview pane.
- When those protocols leak through badly, you can end up seeing raw protocol/base64 garbage instead of an actual image.
- Text-mode renderers are the only reliable workaround inside Television right now.

### Current workaround

For image previews inside Television, use a text-style renderer such as:

- `mcat --ascii < '{}'`
- `chafa --format=symbols '{}'`
- `timg -g70x200 '{}'`

These are compromises. They are useful for recognition, but they are still lower fidelity and may look blocky or pixelated.

### Historical context

Older Television versions had built-in image preview and Nerd Font icon support. That behavior was removed in the `0.12` refactor in favor of a more generic external-command model.

So at the moment there is no known plugin-based fix in this repo's setup. If true high-fidelity image preview inside Television becomes important again, the realistic options are:

- downgrade/pin to an older Television release that still had built-in image previews
- wait for upstream native support to return
- patch/fork Television to integrate a true terminal-image rendering path again
