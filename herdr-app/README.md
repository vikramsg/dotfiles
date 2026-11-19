# Herdr app

The Herdr app (`herdr-app`) is Herdr's desktop window. It runs on its own core,
`hc`, separate from the `herdr` CLI and Sheprd setup in [`herdr/`](../herdr/README.md):
it does not read `config.toml`, its plugins or its prefix keys, and it has its
own spaces and terminals.

## Setup

```sh
just herdr-app
```

This links `settings.json` and `keys.json` into `~/.config/herdr-app/` and
installs the [mods](#mods) (macOS only, with the app open). The app creates both
files on its first start, so on a machine where it has already run, move them
aside first:

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
`herdr/config.toml`, two launchers and the mods' keys. Because the file
is edited, app upgrades no longer add new default shortcuts to it; compare with
`herdr-app commands` after an update and add them by hand.

| Keys | Action | Replaces |
| --- | --- | --- |
| `Cmd+Shift+O` | New OpenCode tab in the current folder | `prefix+Shift+O` |
| `Cmd+Shift+M` | New tab picking and watching a Markdown file with Leaf | `prefix+v` |

Prefix keys are written as key sequences, such as `"ctrl-space %"`:

| Keys | Action |
| --- | --- |
| `prefix+c` / `prefix+1..9` / `prefix+p` | New tab / select tab / previous tab |
| `prefix+$` | Rename the tab |
| `prefix+"` / `prefix+%` | Split down / right |
| `prefix+x` / `prefix+z` | Close / zoom pane |
| `prefix+Arrows` | Focus pane |
| `prefix+Shift+H/J/K/L` | Swap pane |
| `prefix+Shift+C` | New space |
| `prefix+n` / `prefix+w` | New worktree / open a worktree of the space's repo |
| `prefix+g` / `prefix+Shift+O` / `prefix+v` | LazyGit / OpenCode / Leaf tab |
| `prefix+?` | Help |

Default navigation: `Cmd+T` new tab, `Cmd+1..9` tabs, `Ctrl+1..9` spaces,
`Cmd+D` / `Cmd+Shift+D` split right / down, `Cmd+Alt+Arrows` focus pane,
`Cmd+Alt+Shift+Arrows` swap pane, `Cmd+Shift+Enter` zoom, `Cmd+]` / `Cmd+[`
next / previous agent, `Cmd+/` help.

## Mods

Mods of this repository, in `mods/`, linked into the app by `just herdr-app`:

- `nvim-sidebar`: the tab's nvim in a pane right of the focused one. Hiding it
  keeps nvim running, so the next show finds its buffers. While it shows,
  gitview's Enter opens files in it; while hidden, gitview opens its own nvim.
- `files-panel`: the Files panel on a key, as the tab bar's Files button does.
- `worktree-new`, `worktree-open`: Herdr's New and Open worktree dialogs on a
  key, for the focused space, as its space menu opens them.

`herdr-app/justfile` installs two others at pinned versions:

- [herdr-gitview](https://github.com/ChmaraX/herdr-gitview): diffs, staging,
  commits and review notes for agents in the Changes panel.
- [Better Sidebar](https://github.com/munza/herdr-mods/tree/main/better-sidebar):
  the spaces list with each space's branch, its pull request's state and
  worktrees nested under their repository. It runs read-only `git`, and
  `gh pr list` / `gh pr view` with your `gh` login.

| Keys | Action |
| --- | --- |
| `Cmd+E` | Show or hide the tab's nvim |
| `Cmd+Shift+E` | Show or hide the Files panel |
| `Cmd+Shift+G` / `Cmd+G` | gitview in the Changes panel / in a tab of its own |

```sh
just --justfile herdr-app/justfile install    # reinstall the pinned versions
just --justfile herdr-app/justfile uninstall  # stock Changes panel again
```

`gitview.toml` is gitview's config, linked to
`~/.config/herdr/plugins/config/chmarax.gitview/config.toml`. It sets gitview
to 35% of the tab. The nvim sidebar takes half of the focused pane: the app
splits evenly and has no resize command, so drag the divider.

To upgrade, change `gitview_version` or `herdr_mods_commit` in
`herdr-app/justfile` and run `just herdr-app`, with the app open. Installed mods
stay in `~/.config/herdr-app/mods/`, outside this repository. Better Sidebar is
copied, not linked, because Herdr loads a linked mod's code but not its icons.
gitview's installer clones Herdr's `main` layout as `main-copy`, Herdr's own
layouts being read-only; Better Sidebar's step then puts it in place of
`main-copy`'s spaces list.

gitview's installer adds its keys only where free, and replaces the `keys.json`
symlink with a file while doing so. `just herdr-app` copies that file back to
`herdr-app/keys.json` and relinks it, so its keys show up as a change to commit.

## Not carried over

- `prefix+;` (last pane), `prefix+Tab` (Navigator jump back), `prefix+[`
  (copy mode), `prefix+d` (detach) and `prefix+q` (reload): the app has no
  equivalent command; it reloads its files by itself.
- `Ctrl+H/J/K/L` across Neovim splits: `dotfiles.nav-wrap` drives the `herdr`
  CLI. The app's `pane.go` does not know about Neovim, so binding these keys to
  it would break split movement inside Neovim.
- Pane resize keys: the app has no pane resize command; drag the divider.
- Reviewr and Navigator, and the tab bar's branch and host segments: these
  would need app mods. gitview covers most of Reviewr.
- The TokyoNight theme: the app needs a `themes/tokyo-night.json`.
