# Herdr sidebar

`prefix+r` runs the `dotfiles.herdr-sidebar.toggle-reviewr` action. It opens reviewr as a full-height sidebar on the right 40% of the current tab, or closes that tab's sidebar if one is open. Reviewr starts in the invoking terminal's foreground working directory.

`prefix+Shift+R` runs `toggle-reviewr-stack`. It docks the same sidebar but starts reviewr with `--base <parent>`, so the **branch** scope diffs against the current branch's parent in its [gh stack](https://gh.io/stacks) rather than `main`:

| Stack position | Base |
| --- | --- |
| Above an unmerged branch | That branch |
| Above only merged branches, or at the bottom | The stack's trunk |
| Not in a stack | Reviewr's usual base (`origin/HEAD` or its `B` pick) |

The parent comes from `gh stack view --json` filtered with `jq`; both must be on `PATH`, and the action fails with an error in `herdr plugin log list` if either is missing. Reviewr's documentation states that `--base` overrides and disables its `B` picker, so pick the base with the key, not `B`, in that pane.

Reviewr's own `pane` entrypoint takes no arguments, so the pinned launch goes through this plugin's `reviewr-base` pane entrypoint. Herdr gives that pane this plugin's `HERDR_PLUGIN_ID` and `HERDR_PLUGIN_CONFIG_DIR`, and ignores overrides passed when opening it, so the entrypoint's command sets both back to reviewr's (the directory from `herdr plugin config-dir`) before running reviewr's installed `bin/herdr-reviewr`. Reviewr then reads its own `config.toml`.

## Why this exists

Reviewr's own toggle splits only the focused pane, and Herdr has no API that splits a tab at its root. `sidebar.py` gets a full-height column purely by composing public Herdr socket APIs, the same approach the `chmarax.herdr-nvim` sidebar uses:

| Step | Herdr API | Effect |
| --- | --- | --- |
| 1 | `layout.export` | Record the tab's split tree |
| 2 | `pane.move` (`new_tab`) | Park every terminal except the first in an unfocused temporary tab |
| 3 | `plugin.pane.open` | Split the remaining terminal, which now spans the tab, so reviewr is full height |
| 4 | `pane.move` (`tab`) | Move each parked terminal back beside its original sibling at its original ratio; each temporary tab closes as it empties |
| 5 | `layout.set_split_ratio` | Give the sidebar 40% of the tab |

Moves keep the running terminals; nothing is restarted. Closing the sidebar is a plain `pane.close`, after which Herdr gives the width back to the untouched tree on the left. If docking fails partway, the launcher closes the sidebar and rebuilds the original tree.

## Setup and tests

`just herdr` links this directory to `~/.config/herdr-sidebar` and registers it with Herdr. `prefix+r` opens the `pane` entrypoint of the `persiyanov.reviewr` plugin; `prefix+Shift+R` with a stack parent opens this plugin's `reviewr-base` entrypoint. Opening is serialized through `toggle.lock` in the plugin state directory.

```sh
just --justfile bin/herdr_sidebar/justfile test
```
