# Fresh

`just fresh` links `fresh/config.json` and `fresh/init.ts` into `~/.config/fresh/`
and installs Fresh. These links point directly into this repository, so saving
settings through Fresh changes the tracked file here. Run `just herdr` to register
the sidebar launcher, then reload Herdr with `prefix+q`.

The managed config uses Tokyo Night, enables vi mode at startup, and disables Orchestrator mode
and its bundled workspace dock.
With Orchestrator mode disabled, running `fresh` without arguments opens a
regular editor in the current directory instead of attaching to the background
Orchestrator workspace.

## File explorer

`Ctrl+Space`, then `b` opens or focuses a full-height Fresh sidebar on the right
of the current Herdr tab. Existing splits remain together on the left. Fresh
takes 40% of the tab width, starts in the invoking pane's directory, and does
not open automatically on tab or workspace changes. Quit Fresh with `Ctrl+Q`
to remove the sidebar and restore the available width.

Fresh's file explorer is on the right of its editor. `init.ts` focuses it when Fresh is launched by this
sidebar, without changing ordinary Fresh launches. Single-click reuses an
internal preview tab; double-click, Enter, or editing keeps it permanently.
These are Fresh tabs, not Herdr tabs.

Vi mode starts in Normal mode: `i` enters Insert, Escape returns to Normal,
`v` starts Visual selection, and `:w` saves. Your existing Herdr `Ctrl+H/J/K/L`
bindings continue to move between Herdr terminals, rather than Fresh splits.
Use `Ctrl+P` to find Fresh commands such as **Focus Editor** and **Focus File
Explorer**. Herdr's prefix bindings remain available outside Fresh's vi modes.

## Space leader shortcuts

These bindings apply while the editor is in Vim Normal mode, not while typing
in Insert mode or using the file explorer and prompts.

| Keys | Action |
| --- | --- |
| `Space e` | Toggle file explorer |
| `Space s f` | Find a project file |
| `Space s g` | Live project search |
| `Space g d` | Review working-tree Git diff |

In Git diff review, Enter opens the editable working-tree file instead of
opening another diff view. In standalone side-by-side diffs, it opens the
working file even when the cursor is on the historical side. File-filter
prompts retain Enter to accept the filter.

Opening a review shows its changed-files sidebar and hides the project file
explorer. Returning to a file or closing the review restores the project
explorer if it was visible before entering the review. This applies to both
the command palette and `Space g d`.

## Installation

The root `just fresh` recipe delegates installation to `bin/fresh_sidebar`:

- macOS: `brew install fresh-editor`.
- Linux: Fresh's official universal tarball installer, installed under
  `~/.local/share/fresh-editor` with a `~/.local/bin/fresh` link. Desktop-menu
  integration is disabled for this setup. Add `~/.local/bin` to `PATH` if it
  is not already there.

The existing `fresh-editor` entry in the root `Brewfile` is retained for the
normal Homebrew bundle setup.

If a managed target in `~/.config/fresh/` is an existing regular file, `just fresh`
moves it to a uniquely named `.backup.*` file before linking the managed
config. A symlink to a different target or a non-file at that path is left
untouched and reported as an error.

## Upstream references

- [Configuration](https://getfresh.dev/docs/configuration/)
- [File explorer](https://getfresh.dev/docs/features/file-explorer)
- [Workspace restoration](https://getfresh.dev/docs/features/session-persistence#workspace-storage)
- [Fresh installation instructions](https://github.com/sinelaw/fresh#installation)
- [Official installer](https://github.com/sinelaw/fresh/blob/master/scripts/install.sh)
