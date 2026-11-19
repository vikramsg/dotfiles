# Herdr app

The Herdr app (`herdr-app`) is Herdr's desktop window. It runs on its own core,
`hc`, separate from the `herdr` CLI and Sheprd setup in [`herdr/`](../herdr/README.md):
it does not read `config.toml`, its plugins or its prefix keys, and it has its
own spaces and terminals.

## Setup

```sh
just herdr-app
```

This links `settings.json` and `keys.json` into `~/.config/herdr-app/` (macOS
only). The app creates both files on its first start, so on a machine where it
has already run, move them aside first:

```sh
mv ~/.config/herdr-app/settings.json ~/.config/herdr-app/settings.json.before-dotfiles
mv ~/.config/herdr-app/keys.json ~/.config/herdr-app/keys.json.before-dotfiles
just herdr-app
```

Everything else in `~/.config/herdr-app/` is written by the app (its
`AGENTS.md`, type files, shipped layouts and mods, window and view state) and
stays out of this repository. Edits apply live; an invalid file leaves the last
good version running and writes the reason to `settings.error` or `keys.error`.

## Settings

`settings.json` carries over what maps directly from `herdr/`:

| Herdr app | From |
| --- | --- |
| `sounds.enabled: false` | `[ui.sound] enabled = false` |
| `pane_scrollbars: false` | `[ui] pane_scrollbars = false` |
| `copy_on_select: true` | `[ui] copy_on_select = true` |
| `font_size: 12` | Sheprd's `[terminal] size = 12.0` |

The app saves choices made in its Settings window and zoom keys into this file,
in its own field order, so they show up as changes to the repository copy;
commit the ones you want to keep.

## Keys

`keys.json` is the app's default key map plus the `Ctrl+Space` prefix keys from
`herdr/config.toml` and three launchers. Because the file
is edited, app upgrades no longer add new default shortcuts to it; compare with
`herdr-app commands` after an update and add them by hand.

| Keys | Action | Replaces |
| --- | --- | --- |
| `Cmd+Shift+O` | New OpenCode tab in the current folder | `prefix+Shift+O` |
| `Cmd+G` | New LazyGit tab; it closes when LazyGit quits | `prefix+g` popup |
| `Cmd+Shift+M` | New tab picking and watching a Markdown file with Leaf | `prefix+v` |

Prefix keys are written as key sequences, such as `"ctrl-space %"`:

| Keys | Action |
| --- | --- |
| `prefix+c` / `prefix+1..9` / `prefix+n` / `prefix+p` | New tab / select tab / next / previous |
| `prefix+$` | Rename the tab |
| `prefix+"` / `prefix+%` | Split down / right |
| `prefix+x` / `prefix+z` | Close / zoom pane |
| `prefix+Arrows` | Focus pane |
| `prefix+Shift+H/J/K/L` | Swap pane |
| `prefix+Shift+C` / `prefix+w` | New space / space picker |
| `prefix+g` / `prefix+Shift+O` / `prefix+v` | LazyGit / OpenCode / Leaf tab |
| `prefix+?` | Help |

Default navigation: `Cmd+T` new tab, `Cmd+1..9` tabs, `Ctrl+1..9` spaces,
`Cmd+D` / `Cmd+Shift+D` split right / down, `Cmd+Alt+Arrows` focus pane,
`Cmd+Alt+Shift+Arrows` swap pane, `Cmd+Shift+Enter` zoom, `Cmd+]` / `Cmd+[`
next / previous agent, `Cmd+/` help.

## Not carried over

- `prefix+;` (last pane), `prefix+Tab` (Navigator jump back), `prefix+[`
  (copy mode), `prefix+d` (detach) and `prefix+q` (reload): the app has no
  equivalent command; it reloads its files by itself.
- `Ctrl+H/J/K/L` across Neovim splits: `dotfiles.nav-wrap` drives the `herdr`
  CLI. The app's `pane.go` does not know about Neovim, so binding these keys to
  it would break split movement inside Neovim.
- Pane resize keys: the app has no pane resize command; drag the divider.
- Herdr plugins (herdr-nvim, Reviewr, Navigator) and the tab bar's branch and
  host segments: these would need to be rebuilt as app mods.
- The TokyoNight theme: the app needs a `themes/tokyo-night.json`.
