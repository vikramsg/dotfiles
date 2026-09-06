# Differ local review implementation

## Purpose

`<leader>gd` opens the existing automatic local comparison: uncommitted changes against
`HEAD`, or the branch against the merge base with `main` when the working tree is clean.
Comments made in this local review stay local and are exported to:

```text
.agents/reviews/differ-review.json
```

The JSON file is an output artifact. It is not imported into Neovim and local comments
are never sent to GitHub.

## Shortcuts

In a local diff buffer:

- `c` adds a note to the current line.
- Visual selection followed by `c` adds a range note.
- `ge` edits a note anchored under the cursor.
- `gx` deletes a note anchored under the cursor after confirmation.
- Insert-mode `<C-s>` saves the composer. `<Esc>` then `<Enter>` saves from normal mode.
- Normal-mode `q` in the composer cancels only the composer.
- `q` in the diff or file tree closes the review.
- `c` in the file tree retains Differ's native directory-collapse behavior.

In a GitHub PR diff, `c` aliases Differ's configurable native comment action. The
configured native key (currently `ga`) remains available, as do `gp` for replies and
`gx` for deletion. These comments remain native pending GitHub drafts. `<leader>pr`
explicitly starts or resumes a GitHub review and `<leader>ps` submits it.

`g?` shows the applicable local or GitHub destination and shortcuts.

## Design decisions

The local workflow lives in `lua/config/differ_local_review.lua`. It uses Differ's
reusable composer and pure line/range anchor helpers, plus the pure thread formatting
builder. These reusable Differ modules are internal integration points. Local rendering
owns a separate extmark namespace. It does not call the PR
thread refresh path because that path fetches GitHub data and shares global PR display
state.

A local session belongs to one repository and one Differ review lifecycle. Notes are
partitioned by the `HEAD` and `main...` comparisons, so toggling with `B` does not show
anchors against the wrong comparison. The in-memory session is carried across that
toggle. Opening a fresh `<leader>gd` review starts a fresh in-memory note session; the
export is deliberately not imported.

The integration attaches a small rerender callback to the active local view. This
reapplies local extmarks after file changes, refreshes, and layout changes without
patching Differ or replacing its model. Split layout uses compact end-of-line markers;
stacked layout uses expanded local note blocks.

## Export lifecycle

Every successful add, edit, or delete attempts to export a complete snapshot for the
active comparison. The snapshot contains:

- schema version and export timestamp;
- canonical repository root and comparison metadata;
- stable in-session note IDs;
- body and repository-relative file path;
- old/new source-side start and end positions;
- creation and update timestamps.

Before writing, the exporter resolves existing ancestors and refuses path or symlink
escapes outside `.agents/reviews`. It also verifies with `git check-ignore` that the
destination is ignored. The writer creates a private temporary file beside the target,
writes and syncs the complete JSON document, then atomically renames it over the prior
snapshot. A failed export leaves the note in memory, reports the failure, and preserves
the last successful snapshot.

An empty snapshot is exported after deleting the final note. No export occurs merely
from opening a review, switching comparisons, or cancelling, and no JSON is read at
startup. The first saved mutation in a fresh review replaces the previous export.

## Limitations

- Notes exist in memory only for the current Neovim review lifecycle. The JSON is for
  downstream tools, not persistence back into Differ.
- Anchors use source line numbers. If a refresh removes an exact source line, display
  falls back to Differ's nearest rendered line while preserving the exported source
  range.
- Split layout intentionally shows a marker rather than inline blocks to avoid
  desynchronizing the two diff columns.

## Checks performed

From `nvim/`, the full suite passed with a canonical macOS temporary directory:

```sh
TMPDIR=/private/var/folders/p5/zmhxh9795rzd9nn3115zbjb40000gn/T/opencode nvim --headless -u init.lua "+lua require('tests.run').run()" +qa
```

The default temporary path produced a pre-existing Snacks Explorer test failure due
to `/var` versus `/private/var` spelling. Running that test from an archived baseline
reproduced the failure; using the canonical temporary directory resolves it.

New behavioral tests use controlled views and composer callbacks, without automated
keystroke-driven E2E. They cover source-side/range coordinates, multiple notes,
edit/delete/cancel, comparison/repository isolation, zero sidecar calls, ignored and
tracked destinations, symlink escapes, short writes, and preservation on export failure.
Existing local and GitHub UI regression tests also pass. Changed Lua files were formatted
with StyLua; `git diff --check` passes.

Manual verification ran in the separate `differ-verification` Herdr tab against a
disposable Git repository. It exercised real `Space gd`, `c`, both save gestures,
composer cancellation, visual ranges, editing/deletion, stacked/split rendering,
file refreshes, comparison switching, fresh-review export replacement, file-tree
collapse, help scrolling, and closing. Deleted-file old-side and untracked-file
new-side notes exported with the expected paths and coordinates. Exported JSON matched
the saved notes and local edits/deletion made zero sidecar requests.

Using the simulated GitHub backend, `Space pr` opened PR 17, `c` saved a pending
GitHub comment, cancellation left it unchanged, and `Space ps` submitted the selected
verdict and summary. Local JSON was unchanged throughout the GitHub flow.

## Tidy, First rationale

The state, filesystem safety, export schema, and rendering behavior were first isolated
behind one config-local module. The existing `git_review.lua` then needed only lifecycle
ownership and key routing. This keeps local state separate from Differ's GitHub session,
avoids broad monkey-patching, and makes the behavior testable without modifying the
installed plugin.

Coordinator follow-up applied the same small-boundary approach: harden the existing
atomic writer for directory errors and short writes, then test those filesystem effects;
extend the existing help with described live mappings instead of maintaining a second
complete inventory. Remove the misleading pending-draft label from saved local notes.

## Advisory review outcome

A separate background reviewer identified a delayed-callback comparison-ownership gap.
The coordinator accepted it: capture the comparison when opening a composer or note
picker, reject completion after it changes, and verify that edited/deleted notes still
belong to the active collection. Behavioral tests retain composer/picker callbacks,
switch comparisons, and verify that neither notes nor the exported file are changed.
The full suite passed again after this fix. The remaining limitations above are deliberate
parts of the export-only workflow.

## What to look for in review

- Confirm local notes stay attached across file, context, and layout refreshes.
- Confirm `c` clearly opens the LOCAL destination in local diffs and the GITHUB
  destination in PR diffs.
- Confirm `c` still collapses directories in the file tree.
- Confirm save/cancel behavior in both insert and normal composer modes.
- Confirm failed exports retain in-memory notes and do not replace the prior JSON.
