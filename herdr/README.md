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
| `prefix+Tab` | Jump back to the previous workspace visited through Navigator |
| `prefix+[` | Enter copy mode |
| `prefix+c` | Create a tab |
| `prefix+1..9` | Switch tabs |
| `prefix+p` / `prefix+n` | Previous / next tab |
| `prefix+$` | Rename the current tab |
| `prefix+"` / `prefix+%` | Stacked / side-by-side split |
| `prefix+Shift+1..9` | Focus agent 1–9 |
| `prefix+s` | Open Herdr Navigator |
| `prefix+w` | Workspace navigation |
| `prefix+Shift+C` | Create a workspace |
| `prefix+q` / `prefix+?` / `prefix+d` | Reload config / help / detach |
| `prefix+e` / `prefix+f` | Toggle the nvim sidebar / open the nvim file picker |
| `prefix+r` | Toggle the full-height reviewr sidebar on the right |
| `prefix+v` | Pick and watch a Markdown file in a popup |
| `prefix+g` | Open the LazyGit popup |
| `prefix+Shift+T` | Open the terminal popup |
| `prefix+Shift+O` | Append OpenCode and nvim project tabs |

## Setup

```sh
just brew
just bin
just herdr
herdr
```

`just herdr` links `config.toml`, links `herdr/plugin/nav_wrap/` to the
`~/.config/herdr-nav-wrap` anchor, and registers it with Herdr. It does the same for `bin/herdr_sidebar/`, which backs `prefix+r`: it docks reviewr full height on the right, so keep `persiyanov.reviewr` in `plugins.json`. Reviewr still reads its own `config.toml` from `herdr plugin config-dir persiyanov.reviewr`. Herdr's logs,
sockets, and persistent session data remain in the normal `~/.config/herdr`
directory and outside this repository. `just bin` links `~/.local/bin/pbcopy` so `persiyanov.reviewr` forwards clipboard copies over OSC 52 through Herdr instead of invoking `xclip` on headless Linux VMs. The plugin's `navigate.sh` and the
repository's `nvim/` adapter share `focus-wrap.sh`, so start Neovim once after
linking `nvim/`.

## Updates

The Herdr application is managed by Homebrew through the root `Brewfile`. Update it with `brew upgrade herdr`, not `herdr update`, to keep Homebrew as the owner of the executable. Avoid a separate `~/.local/bin/herdr`, which can shadow the Homebrew binary.

Update GitHub plugins separately:

```sh
just --justfile herdr/justfile update
```

Plugins declared without a `ref` in `herdr/plugins.json` follow their upstream default branch. `just herdr` installs missing plugins but does not update existing ones. Upgrading the executable does not restart running Herdr sessions.

## Navigator Jump Back

`prefix+Tab` invokes `herdr-navigator.jump-back`, toggling between the current workspace and the previous workspace remembered by [Herdr Navigator](https://github.com/thanhdat77/herdr-navigator). It records local workspace changes made through Navigator, not clicks in Herdr's sidebar or switches through other tools. The native `prefix+;` last-pane shortcut is unchanged.

Open Navigator with `prefix+s`, from Herdr's plugin actions, or run:

```sh
herdr plugin action invoke herdr-navigator.open
```

Navigate to another local workspace through the picker before using Jump Back. The previous workspace stays pinned at the top only while the picker is unfiltered. Navigator replaces Herdr's native goto and Settings bindings on `prefix+s`; the GUI's `Cmd+,` Settings shortcut remains available. `prefix+w` still opens Herdr's workspace picker, whose switches do not populate Navigator history.

Edit `herdr/navigator.toml` for persistent Navigator settings. `just herdr` links it to `~/.config/herdr/plugins/config/herdr-navigator/config.toml` before installing the plugin. Move or migrate an existing unmanaged config before linking. Only the Jump Back settings are overridden; other settings use Navigator's defaults. Installation builds the plugin with Rust and Cargo; it does not require Bun. Reload Herdr with `prefix+q` after setup to activate the shortcut.

## macOS GUI

On macOS 14.2 or newer, `just brew` also installs the signed, notarized Herdr GUI from `penso/tap`. Linux installs only the Herdr daemon, not the GUI or its Homebrew tap.

```sh
open -a Herdr
```

The GUI connects to the separately installed Herdr daemon. Closing the GUI leaves daemon sessions running. Update the GUI with `brew upgrade --cask herdr-gpui`.

On macOS, `just herdr` links `config-gpui.local.toml` into `~/.config/herdr/`. Move or migrate an existing unmanaged override file before linking. Edit the repository file for persistent GUI settings; the app reloads saved changes automatically. The managed `config-gpui.toml` defaults are owned by the app and must not be edited.

The GUI uses `TokyoNight Storm` and the `comfortable-rounded` sidebar layout, which shows branches for workspaces and linked worktrees. Herdr's default sidebar rows request branch updates from the daemon; reload the daemon configuration with `prefix+q` after changing it. For faster discrete mouse-wheel scrollback, set `mouse_scroll_lines` under `[ui]` in `herdr/config.toml` (default `3`). This does not change precise trackpad movement or scrolling inside applications that consume mouse events themselves.

Existing Zsh panes that loaded the former branch reporter continue publishing unused metadata until their shells restart. Native sidebar rows do not use that metadata.

`Cmd+Shift+B` opens a new browser tab in the GUI.

### Separate windows per session

With the GUI already running, use the [Zsh helper](../zsh/README.md#herdr-shortcuts) to open another window attached to `dot` without switching the existing `default` window:

```sh
herdr-gpui dot
```

The helper runs the installed app bundle's command:

```sh
"/Applications/Herdr.app/Contents/MacOS/Herdr" window new --session dot
```

Replace `dot` with another local session name as needed. This uses the running app's native multi-window support; it does not require another app instance or restarting an existing session. See the upstream [window commands](https://github.com/penso/herdr-gpui/blob/main/docs/cli.md#app-and-windows).

A separate GUI window still loads the shared saved-machine list; it does not use the isolated client state from the `herdr-dot` shell shortcut. Choose **Local** in the bottom-left device picker to filter remote workspaces and agents out of that window's sidebar without removing or disabling `vm-us`. This filter is window-local, not a separate machine catalog. See the upstream [GUI documentation](https://github.com/penso/herdr-gpui/blob/main/crates/herdr-gpui/README.md).

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
