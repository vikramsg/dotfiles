# Herdr

Herdr is a persistent terminal multiplexer that coexists with tmux. This
configuration keeps the useful tmux key habits while leaving the tmux and
Neovim configurations independent and unchanged.

## Setup

```sh
just brew
just herdr
herdr
```

`just herdr` links only `config.toml`. Herdr's logs, sockets, and persistent
session data remain in the normal `~/.config/herdr` directory and outside this
repository.

## Keys

The prefix is `Ctrl+Space`.

| Keys | Action |
| --- | --- |
| `Ctrl+H/J/K/L` | Focus the pane left / down / up / right |
| `prefix+q` | Reload configuration |
| `prefix+?` | Show help |
| `prefix+d` | Detach |
| `prefix+[` | Enter copy mode |
| `prefix+c` | Create a tab |
| `prefix+1..9` | Switch tabs |
| `prefix+p` / `prefix+n` | Previous / next tab |
| `prefix+$` | Rename the current tab |
| `prefix+v` | Pick and watch a Markdown file in a popup |
| `prefix+"` / `prefix+%` | Stacked / side-by-side split |
| `prefix+x` / `prefix+z` | Close / zoom pane |
| `prefix+;` | Focus the last pane |
| `prefix+Shift+C` | Create a workspace |
| `prefix+h/l/k/j` | Resize left / right / down / up |
| `prefix+Shift+H/J/K/L` | Swap left / down / up / right |

Pane focus is spatial but does not cross Neovim splits. The direct bindings also
replace shell behavior such as `Ctrl+K` kill-line and `Ctrl+L` clear-screen
while Herdr is active. Resize commands use Herdr's default step and are not
repeat-mode bindings, so press the prefix for each resize.

## Intentional differences from tmux

- Herdr has only the `Ctrl+Space` prefix; tmux also retains `Ctrl+B`.
- Herdr cannot create the tmux upward split bound to `prefix+'`.
- Herdr has no complete equivalent to moving a window into an arbitrary named
  session with tmux's `prefix+M` flow.
- Herdr uses its native sidebar and tab UI instead of gitmux and battery status.
- Herdr's native persistence replaces tmux-resurrect and tmux-continuum rather
  than copying their implementation.
- Pane navigation does not integrate with Neovim splits.

Reload a running session with `prefix+q` or `herdr server reload-config`.
