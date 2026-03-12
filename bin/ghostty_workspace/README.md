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
```

## Testing

```bash
uv run --package ghostty-workspace pytest -c bin/ghostty_workspace/pyproject.toml
```
