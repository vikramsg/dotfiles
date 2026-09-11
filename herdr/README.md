# Herdr

Herdr is a persistent terminal multiplexer that coexists with tmux. This
configuration adds seamless Neovim split navigation while preserving the
existing tmux key habits and configuration.

## Shortcuts

The prefix is `Ctrl+Space`.

| Keys | Action |
| --- | --- |
| `Ctrl+H/J/K/L` | Navigate left / down / up / right across Neovim splits and Herdr panes, wrapping at pane edges |
| `prefix+←` / `prefix+↓` / `prefix+↑` / `prefix+→` | Focus pane left / down / up / right |
| `prefix+h/l/k/j` | Resize pane left / right / down / up |
| `prefix+Shift+H/J/K/L` | Swap pane left / down / up / right |
| `prefix+x` / `prefix+z` | Close / zoom pane |
| `prefix+;` | Focus the last pane |
| `prefix+[` | Enter copy mode |
| `prefix+c` | Create a tab |
| `prefix+1..9` | Switch tabs |
| `prefix+p` / `prefix+n` | Previous / next tab |
| `prefix+$` | Rename the current tab |
| `prefix+"` / `prefix+%` | Stacked / side-by-side split |
| `prefix+Shift+1..9` | Focus agent 1–9 |
| `prefix+s` | Session navigator (goto) |
| `prefix+w` | Workspace navigation |
| `prefix+Shift+C` | Create a workspace |
| `prefix+q` / `prefix+?` / `prefix+d` | Reload config / help / detach |
| `prefix+e` / `prefix+f` | Toggle the nvim sidebar / open the nvim file picker |
| `prefix+r` | Toggle the reviewr pane |
| `prefix+v` | Pick and watch a Markdown file in a popup |
| `prefix+g` | Open the LazyGit popup |
| `prefix+Shift+T` | Open the terminal popup |
| `prefix+Shift+D` | Open the current repository in a new Hunk tab |
| `prefix+Shift+G` | Review the current PR in a new tab |
| `prefix+Shift+O` | Append OpenCode and nvim project tabs |

## Setup

```sh
just brew
just tuicr
just herdr
herdr
```

`just herdr` links `config.toml`, links `herdr/plugin/nav_wrap/` to the
`~/.config/herdr-nav-wrap` anchor, and registers it with Herdr. Herdr's logs,
sockets, and persistent session data remain in the normal `~/.config/herdr`
directory and outside this repository. The plugin's `navigate.sh` and the
repository's `nvim/` adapter share `focus-wrap.sh`, so start Neovim once after
linking `nvim/`. Interactive
Zsh panes publish a compact ` branch` label for the Spaces sidebar.

## Remote attach

Use the remote server's keybindings when attaching directly from another
machine:

```sh
herdr --remote vm-us --remote-keybindings server
```

`herdr --remote` otherwise defaults to local keybindings and intentionally does
not send local custom command bindings to the remote host. As a result, popup
and shell bindings from this configuration, such as the LazyGit popup, are not
available. Using `--remote-keybindings server` loads those bindings from
`vm-us` and makes the session behave like running `herdr` after connecting with
SSH.

## Keys

Quitting Hunk with `q` closes its tab and returns to the tab it was opened from,
rather than leaving a shell prompt. If the original tab was closed in the
meantime, Herdr uses its normal tab-close behavior.

`dotfiles.nav-wrap` gives Neovim the chord first and crosses into a Herdr pane
only at a split edge. When it reaches a Herdr pane edge it wraps to the far
edge, matching tmux's `select-pane` behavior. The Neovim adapter falls back to
`vim-tmux-navigator` inside tmux and to plain split movement outside either
multiplexer. The direct bindings replace shell behavior such as `Ctrl+K`
kill-line and `Ctrl+L` clear-screen while Herdr is active. Resize commands use
Herdr's default step and are not repeat-mode bindings, so press the prefix for
each resize.

## Troubleshooting

### `Ctrl+h/j/k/l` does nothing inside Neovim

- Confirm the Neovim adapter loaded:
  ```vim
  :map <C-l>
  ```
  Expect a mapping described as `Navigate right (dotfiles.nav-wrap)`.
- If it is missing, restart Neovim or run `:Lazy sync`, then check for errors:
  ```vim
  :messages
  ```
- Confirm Herdr is healthy:
  ```sh
  herdr config check
  herdr plugin list
  ```
  Expect `dotfiles.nav-wrap` enabled.
- If it only fails inside the `chmarax.herdr-nvim` sidebar (`prefix+e`), know how the sidebar is wired:
  - The visible pane is a `nvim --remote-ui` client attached to a per-tab headless daemon, `nvim --headless --listen /run/user/<uid>/herdr-nvim/<tab>.sock`.
  - The navigation adapter runs in that daemon, not in the visible client.
  - The socket is keyed by tab id only, so sessions sharing a tab id (`dot` and `dotfiles`, both `w1:t1`) share one daemon.
  - The daemon captures `HERDR_SESSION`, `HERDR_SOCKET_PATH`, and `HERDR_PANE_ID` once when it starts; if those are stale, `Ctrl+h/j/k/l` silently does nothing.
- Reset the stale daemon:
  ```sh
  # toggle the sidebar off first: prefix+e
  pkill -f '[n]vim --headless --listen.*herdr-nvim'
  rm -rf /run/user/$UID/herdr-nvim
  ```

## Intentional differences from tmux

- Herdr has only the `Ctrl+Space` prefix; tmux also retains `Ctrl+B`.
- Herdr cannot create the tmux upward split bound to `prefix+'`.
- Herdr has no complete equivalent to moving a window into an arbitrary named
  session with tmux's `prefix+M` flow.
- Herdr uses its native sidebar and tab UI instead of gitmux and battery status.
- Herdr's native persistence replaces tmux-resurrect and tmux-continuum rather
  than copying their implementation.
- Herdr/Neovim navigation is provided by the repo-local `dotfiles.nav-wrap`
  plugin and requires `jq`; without `jq`, Herdr pane movement still works but
  Vim process detection does not.

Reload a running session with `prefix+q` or `herdr server reload-config`.
