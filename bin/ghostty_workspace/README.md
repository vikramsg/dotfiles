# ghostty-workspace

Open a Ghostty window using declarative TOML workspace files.

## Install

From this repo:

```bash
uv tool install ./bin/ghostty_workspace --force
```

After local updates:

```bash
uv tool install ./bin/ghostty_workspace --force --no-cache
```

## Config Location

By workspace name, the tool looks in:

- `~/.config/ghostty/workspaces/<name>.toml`

You can also pass an explicit file path with `--config`.

Repo example config:

- `ghostty/workspaces/example.toml`

## Example Config

```toml
path = "~/Projects/Personal/dotfiles"
focus_tab = 2

[[tabs]]
name = "tab1"
command = "nvim ."

[[tabs]]
name = "tab2"
path = "./ghostty"
command = "pwd"
```

Fields:

- `path` (optional): global default working directory for all tabs
- `focus_tab` (optional, default `1`): 1-based tab index to focus
- `[[tabs]]` (required): tab definitions
  - `name` (optional): tab title, defaults to `tabN`
  - `command` (optional): shell command to run before dropping into login shell
  - `path` (optional): per-tab path override (absolute, relative to global `path`, or relative to config directory)

## Usage

```bash
# Resolves ~/.config/ghostty/workspaces/dev.toml
ghostty-workspace dev

# Uses an explicit config file
ghostty-workspace --config ~/.config/ghostty/workspaces/dev.toml

# Uses the repo example config directly
ghostty-workspace --config ~/Projects/Personal/dotfiles/ghostty/workspaces/example.toml
```

## Deterministic Tab Order And Focus

For deterministic workspace startup, set this in your Ghostty config:

```ini
window-new-tab-position = end
```

Why this is required:

- `current` inserts each new tab after the currently focused tab.
- During scripted startup, focus can shift while tabs initialize.
- `end` always appends tabs, so TOML order is preserved.

The CLI focuses tabs using Ghostty action `goto_tab:N` (via AppleScript `perform action`) instead of `select tab (...)` for reliable focus.

If order or focus still looks wrong, rerun with `ghostty/workspaces/example.toml` to verify behavior against the known-good sample in this repo.

## Testing

```bash
uv run pytest
```

Run from the package directory: `bin/ghostty_workspace`.
