# Differ local review implementation

## Shape

`config/git_review.lua` owns Differ integration: opening local comparisons, buffer
mappings, and the non-file **Review output** sidebar rows. Local note behavior lives in
`config/differ_local_review.lua`; persistence and validation remain isolated in
`config/differ_local_review_store.lua`.

Each canonical repository and branch has one schema-version 2 document at:

```text
.agents/reviews/review-<12-character identity SHA>.json
```

The hash input includes the identity kind and branch name, or the detached commit. A
branch's recorded `head` is informational, so commits and pushes do not rename its file.
The stored owner is checked when loading and saving; a short-hash collision therefore
protects the existing document instead of opening or overwriting another branch's data.

The document contains separate `HEAD` and `main...` comparison groups. Notes retain
their ID, body, repository-relative path, old/new range, timestamps, captured source
context, and evaluated anchor status. Exact captured source text prevents a stale note
from moving to unrelated code. Missing or changed text is outdated; insufficient
context is unverified.

The standalone contract is `schemas/differ-review.schema.json`. Runtime validation
rejects malformed, unsupported, unknown-field, and wrong-owner documents before any
write. Saves compare the loaded byte fingerprint with the current file, write and fsync
a private neighboring file, then atomically rename it. This preserves the prior snapshot
on encoding, partial-write, or rename failure and prevents stale sessions from replacing
newer data.

## Sidebar integration

The output rows are appended after Differ renders its `FileEntry` sections and use
dedicated metadata. They never enter file counts, staging/discard actions, or file
navigation. The path and filename occupy separate rows so a 35-column sidebar shows:

```text
Review output (1)
  .agents/reviews/
    review-123456789abc.json
```

The local open path binds the canonical review session directly to the panel. This is
important because Differ's panel root is display-formatted with `:~` (for example
`~/Projects/…`), while persistence uses a canonical absolute root. The previous lookup
compared those representations and omitted the complete section even though the panel
adapter was attached. Refresh now follows the bound session rather than reconstructing
ownership from the display root.

`Enter` on the output row opens a read-only JSON split; `q` closes it. Successful saves
rerender the owning panel and refresh matching open output buffers. Other `Enter` rows
continue through `Panel:select(true)`, which focuses file diffs and preserves directory
fold toggling for local and GitHub panels.

## Session safety

Composer, picker, confirmation, and comparison callbacks retain their originating
session and comparison and recheck branch ownership before mutation. Local operations
never call the GitHub sidecar. Opening, comparison switching, and review reopening do
not clear notes; only the confirmed branch reset clears both comparison groups.

This PR's earlier legacy importer, marker, scans, source snapshot duplication, migration
metadata, and `legacy-v1` source representation were removed because the feature has not
been released. Existing development data is converted once outside the runtime: retain
the document owner/timestamps/comparisons and every note's ID, body, path, range,
timestamps, context text, and status; remove top-level `migration` and
`source_context.origin`; write it to the new short filename. No converter ships.

## Tidy, First

The change removes compatibility machinery before adjusting the filename and sidebar.
It also folds the 130-line output-only runtime module into the existing Differ integration
instead of adding another abstraction. Persistence stays separate because filesystem
confinement, validation, atomic replacement, and conflict detection form a coherent
safety boundary rather than UI behavior.

## Verification evidence

The fixed acceptance checklist remains unchanged in `.agents/plans/differ-local-review.md`.
The coordinator verified the following in the separate `differ-simplify-e2e` Herdr tab:

| Requirements | Observed result |
| --- | --- |
| 1, 5 | Dirty checkout opened `HEAD`; clean checkout opened `main...`. `B` kept comments separate. Closing/reopening and a full Neovim restart after committing and pushing to a disposable bare remote retained both groups and the same filename. |
| 2, 3 | Line and three-line range comments saved with both gestures; upward visual draft cancellation left the saved notes intact. Multiple notes rendered together; the picker selected a note for editing. Cancelled deletion retained it; confirmed deletion removed it. Stacked bodies and split markers worked. |
| 4, 8, 16 | The short JSON existed on disk. Clipboard inspection matched its absolute path from both diff and sidebar, including after changing cwd. Unsaved branches reported no saved file; ordinary `Space cp` copied the source path. |
| 5, 6 | Beta opened empty, saved its own comment, and resumed it. Cancelled reset kept it; confirmed reset persisted an empty review on reopening. Returning to alpha restored its notes. A second repository started independently. |
| 7, 9 | Changing only the middle of a commented range marked it outdated in memory, saved JSON, and the already-open read-only output split. |
| 9, 10, 16 | Reproduced the missing output in the actual dotfiles repository before the fix. Afterwards its tilde-formatted root displayed `.agents/reviews/` and `review-29476e119758.json` at 35 columns without focusing the sidebar first, in both comparisons. Enter opened that exact file read-only; `q` closed the split. The section survived refresh and tree hide/show. Directory Enter toggled folding; file Enter focused the diff, including in a PR. Output-row staging/discard left the disposable Git worktree unchanged. |
| 11 | Local operations made zero sidecar requests. A simulated PR accepted one draft and one submission; cancelling another draft posted nothing. The local JSON remained byte-identical through the GitHub flow. |
| 12 | Switching branches while composing rejected the old draft. An external writer updated JSON while another composer was open; submission preserved the newer disk bytes and retained the unsaved draft in memory. |
| 13 | The converted actual review and test snapshots passed the standalone JSON Schema validator. |
| 14, 15 | Read the help in the live review and checked the README as a usage guide. Removed the storage-design and output-routing prose from the README. |

The four actual user comments were copied to `review-29476e119758.json` after backing up
the previous files outside the repository. A structural comparison confirmed all comment
content, IDs, locations, timestamps, comparison membership, and document metadata survived;
only the removed development-migration fields were stripped. The originals were untouched.

The full headless Neovim suite, real JSON Schema checks, StyLua, and `git diff --check`
passed. Automated regressions use direct callbacks, repository/filesystem effects, and
the actual schema validator. They include tilde-display-root ownership, shorter filename
stability, wrong-owner collision protection, stale writes, invalid data, partial writes,
and rename failure. No new automated keystroke tests or copy/change-detection assertions
were added. The separate live tests above establish the UI behavior.

The background advisory reviewer found one concrete contract gap: the schema accepted
swapped comparison metadata that the runtime rejected. Fixed per-key `spec`, `base`, and
note-context constraints; negative validator cases now exercise swapped comparisons and
misplaced notes. No broader redesign was indicated. During the coordinator's read-through,
an invalid-file inspection gap was also corrected: readable protected files remain in the
sidebar and support path-copy while writes remain blocked. A fresh manual session verified
an unsupported-version file could be opened read-only and its actual path copied. The
full suite and formatting checks passed after these fixes.

Run from `nvim/` (canonical macOS TMPDIR avoids the existing explorer path-alias issue):

```sh
TMPDIR=/private/var/folders/p5/zmhxh9795rzd9nn3115zbjb40000gn/T/opencode \
  nvim --headless -u init.lua "+lua require('tests.run').run()" +qa
```

## What to look for in review

- Confirm short filenames remain stable across restart, commit, and push, while branches
  and repositories remain isolated and wrong-owner documents are protected.
- Confirm the actual filename appears beneath `.agents/reviews/` at 35 columns without
  becoming a file action/count/navigation target.
- Confirm output opens read-only JSON, refreshes after saves, and remains visible when
  Differ uses a tilde-formatted display root.
- Exercise stale composers and two open sessions; newer bytes and unsaved drafts must
  survive rejected writes.
- Verify local comments never cross the GitHub backend boundary and file `Enter` still
  focuses diffs in both local and PR sidebars.
