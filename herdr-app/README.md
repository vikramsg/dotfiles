# Herdr app

The Herdr app (`herdr-app`) is Herdr's desktop window. It runs on its own core,
`hc`, separate from the `herdr` CLI and Sheprd setup in [`herdr/`](../herdr/README.md):
it does not read `config.toml`, its plugins or its prefix keys, and it has its
own spaces and terminals.

## Setup

```sh
just herdr-app
```

This links `settings.json`, `keys.json`, `themes/` and `mods/` into `~/.config/herdr-app/` and
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
| `theme: "tokyo-night"` | `[theme] name = "tokyo-night"`; the theme is `themes/tokyo-night.json` |
| `colors` | `[theme.custom]`: `accent`, `sidebar_bg` as `chrome`, `active_row_bg` as `selected`, `selection_bg` as `selection` |

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
| `prefix+g` / `prefix+Shift+O` / `prefix+v` | Ziggity / OpenCode / Leaf tab |
| `prefix+?` | Help |

Default navigation: `Cmd+T` new tab, `Cmd+1..9` tabs, `Ctrl+1..9` spaces,
`Cmd+D` / `Cmd+Shift+D` split right / down, `Cmd+Alt+Arrows` focus pane,
`Cmd+Alt+Shift+Arrows` swap pane, `Cmd+Shift+Enter` zoom, `Cmd+]` / `Cmd+[`
next / previous agent, `Cmd+/` help.

## Mods

Mods of this repository, in `mods/`, linked into the app by `just herdr-app`:

- `app-sidebar`: a full-height sidebar between the panes and the right panel,
  showing one terminal app at a time. Each tab has its own instance of each app,
  started on the tab's machine in its focused pane's folder; hiding the sidebar
  leaves the app running, and switching tabs shows that tab's app or hides the
  sidebar. The apps are in `mods/app-sidebar/apps.js`: add one there and bind a
  key to `app-sidebar.toggle:<name>`. While the sidebar shows nvim on this Mac,
  gitview's Enter opens files in it; on the VM gitview opens its own nvim.
- `spacer`: draws nothing, for a layout block that only takes up room (the app requires every block to hold content).
- `files-panel`: the Files panel on a key, as the tab bar's Files button does.
- `worktree-new`, `worktree-open`: Herdr's New and Open worktree dialogs on a
  key, for the focused space, as its space menu opens them.

`herdr-app/justfile` installs four others at pinned versions:

- [herdr-gitview](https://github.com/ChmaraX/herdr-gitview): diffs, staging,
  commits and review notes for agents in the Changes panel.
- [Space Ports](https://github.com/teknologist/herdr-space-ports): Herdr's own spaces list (worktrees under their repository, branch and ahead/behind) with each space's listening ports under it, then, faded, the machine's other ports started from a terminal. Clicking a port opens `http://localhost:<port>/`; for a space on the VM it first forwards the port with `ssh -L` (a herdr-core terminal that outlives the window; right-click the port to stop it). Every 5 seconds it runs `ss` (Linux) or `lsof` (macOS) and `ps` on each machine with a space.
- [filetree](https://github.com/cybertron288/herdr-mods/tree/main/filetree):
  the panel's Files tab, in place of Herdr's own tree. It follows the focused
  terminal's folder, also on the VM, and shows the branch, changed files with
  `+N −N`, a filter that searches unopened folders, and a preview. It runs
  read-only `git`, `ls` and `du`. Its optional Claude Code hook (`bridge.ts`,
  for the Recent tab) is left off. Enter or a double-click opens the file in
  the tab's sidebar nvim (`app-sidebar.open:<path>`, set as its config's
  `open`), starting it if needed, on this Mac or the VM. Upstream filetree only previews files in a VM space; `just herdr-app` patches that out. `p` still previews.
- [usage-limits](https://github.com/nozikov/herdr-usage-limits): Claude Code's and Codex's 5-hour and weekly limits in the status bar, which `just herdr-app` splits into thirds: Herdr's own status, the limits (ending two thirds across), and the `spacer` mod; hover for every limit, the focused agent's session, and OpenCode's tokens today and over 7 days. Every 5 minutes it asks the `claude` and `codex` CLIs for their limits (no prompt, so no tokens), and reads OpenCode's database read-only. ⚙ in the hover panel picks what the bar shows.

| Keys | Action |
| --- | --- |
| `Cmd+E` / `prefix+r` | Show or hide the tab's nvim / reviewr in the sidebar |
| `Cmd+Shift+E` | Show or hide the Files panel |
| `Cmd+Shift+G` / `Cmd+G` | gitview in the Changes panel / in a tab of its own |

```sh
just --justfile herdr-app/justfile install    # reinstall the pinned versions
just --justfile herdr-app/justfile uninstall  # stock Changes panel again
```

`gitview.toml` is gitview's config, linked to
`~/.config/herdr/plugins/config/chmarax.gitview/config.toml`. It sets gitview
to 35% of the tab. The sidebar takes 40% of the width beside the right
panel (weight 0.6667 against the panes' 1). Showing the sidebar sets both weights again, since the app rewrites them when the panel or sidebar is shown or hidden; a width dragged by hand lasts until the sidebar is next shown.

To upgrade, change `gitview_version`, `space_ports_commit`, `filetree_commit` or `usage_limits_commit`
in `herdr-app/justfile` and run `just herdr-app`, with the app open. Installed
mods stay in `~/.config/herdr-app/mods/`, outside this repository. Space
Ports, filetree and usage-limits are copied, not linked, because Herdr loads a linked mod's
code but not its icons, and draws a linked usage-limits blank. gitview's installer clones Herdr's `main` layout as
`main-copy`, Herdr's own layouts being read-only; Space Ports' step then
puts it in place of `main-copy`'s spaces list, filetree's puts filetree in the
Files tab, and the app sidebar's adds its block and the hidden floating copy
that takes its keys.

gitview's installer adds its keys only where free, and replaces the `keys.json`
symlink with a file while doing so. `just herdr-app` copies that file back to
`herdr-app/keys.json` and relinks it, so its keys show up as a change to commit.

## Profiles

A profile is a second Herdr window whose spaces, tabs and terminals are kept apart from the main window's, with the same setup:

```sh
herdr_profile work            # open (or bring forward) the "work" window; --help explains it
just herdr-app-profile work   # set up or refresh its home without opening it
```

`herdr_profile` is defined in `zsh/.zshenv`. It starts the app with two variables, as Herdr's own `scripts/sandbox` does to run a second app:

- `HC_SESSION=<name>`: the window's terminals run in a herdr-core session of their own. Spaces, tabs and panes are stored there, so they are per profile.
- `HERDR_APP_HOME=~/.config/herdr-app-<name>`: the window's own home, which the app allows one window each.

The profile's home gets the main home's setup:

| Item | In the profile's home |
| --- | --- |
| `settings.json`, `keys.json`, `themes/`, the mods in `herdr-app/mods/` | linked to this repository, so edits reach every window |
| gitview, Space Ports, filetree, file-icons and usage-limits | copied from `~/.config/herdr-app/mods/`, as linked mods lose their icons |
| `layouts/main-copy.json` | copied from the main home with the sidebar block hidden and empty, since the sidebar records which terminal it shows in the layout |
| `shared.json` (mod state and the window's layout), `view.json`, `window.json`, `data/` | the window's own; a new profile starts on `main-copy` |
| Machines (`hc machine ls` in the profile's session) | the main session's machines, each reached in a session of the profile's name there, so the profile's VM spaces are apart from the main window's |

`just herdr-app` refreshes every `~/.config/herdr-app-*` home after the main one. A refresh copies `main-copy` again, so a sidebar width dragged in a profile's window goes back to the main window's.

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
