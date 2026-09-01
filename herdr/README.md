# Herdr

Herdr is a persistent terminal multiplexer that coexists with tmux. This
configuration adds seamless Neovim split navigation while preserving the
existing tmux key habits and configuration.

## Setup

```sh
just brew
just tuicr
just herdr
herdr plugin install paulbkim-dev/vim-herdr-navigation --ref 79679dacc791f70fc34de8b29a3cf9706c0f5b2f -y
herdr
```

`just herdr` links only `config.toml`. Herdr's logs, sockets, and persistent
session data remain in the normal `~/.config/herdr` directory and outside this
repository. The separate plugin command installs the audited
`vim-herdr-navigation` revision into Herdr's managed plugin directory. Start
Neovim once after linking `nvim/` so Lazy installs the matching editor adapter.
Interactive Zsh panes publish a compact ` branch` label for the Spaces sidebar.

## Keys

The prefix is `Ctrl+Space`.

| Keys | Action |
| --- | --- |
| `Ctrl+H/J/K/L` | Navigate left / down / up / right across Neovim splits and Herdr panes |
| `prefix+q` | Reload configuration |
| `prefix+?` | Show help |
| `prefix+d` | Detach |
| `prefix+[` | Enter copy mode |
| `prefix+c` | Create a tab |
| `prefix+1..9` | Switch tabs |
| `prefix+Shift+1..9` | Focus agents |
| `prefix+p` / `prefix+n` | Previous / next tab |
| `prefix+$` | Rename the current tab |
| `prefix+v` | Pick and watch a Markdown file in a popup |
| `prefix+"` / `prefix+%` | Stacked / side-by-side split |
| `prefix+x` / `prefix+z` | Close / zoom pane |
| `prefix+;` | Focus the last pane |
| `prefix+Shift+C` | Create a workspace |
| `prefix+h/l/k/j` | Resize left / right / down / up |
| `prefix+Shift+H/J/K/L` | Swap left / down / up / right |
| `prefix+Shift+G` | Review the current PR in a new tab |

`vim-herdr-navigation` gives Neovim the chord first and crosses into a Herdr pane
only at a split edge. Its Neovim adapter falls back to `vim-tmux-navigator`
inside tmux and to plain split movement outside either multiplexer. The direct
bindings replace shell behavior such as `Ctrl+K` kill-line and `Ctrl+L`
clear-screen while Herdr is active. Resize commands use Herdr's default step and
are not repeat-mode bindings, so press the prefix for each resize.

## Intentional differences from tmux

- Herdr has only the `Ctrl+Space` prefix; tmux also retains `Ctrl+B`.
- Herdr cannot create the tmux upward split bound to `prefix+'`.
- Herdr has no complete equivalent to moving a window into an arbitrary named
  session with tmux's `prefix+M` flow.
- Herdr uses its native sidebar and tab UI instead of gitmux and battery status.
- Herdr's native persistence replaces tmux-resurrect and tmux-continuum rather
  than copying their implementation.
- Herdr/Neovim navigation requires `vim-herdr-navigation` and `jq`; without
  `jq`, Herdr pane movement still works but Vim process detection does not.

Reload a running session with `prefix+q` or `herdr server reload-config`.
