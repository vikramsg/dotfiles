# Differ local review implementation

## Purpose and workflow

`<leader>gd` opens the automatic local comparison: uncommitted changes against `HEAD`,
or the branch against the merge base with `main` when the working tree is clean. Local
notes are persistent and never use Differ's GitHub sidecar.

In a local diff:

- `c` adds a line note; visual `c` adds a range note.
- `ge` edits and `gx` deletes a note under the cursor.
- insert `<C-s>` or normal `<Enter>` saves the composer; normal `q` cancels it.
- `B` changes between `HEAD` and `main...` notes in the same branch document.
- `<leader>cr` copies the absolute saved JSON path without changing `<leader>cp`.
- `<leader>cR` confirms and resets both comparisons for this branch.

In the file sidebar, `Enter` opens a file and focuses its diff; on a directory it keeps
Differ's fold toggle. `c` retains Differ's native close-directory behavior. `g?` shows
the applicable local or GitHub controls. GitHub reviews remain separate: `<leader>pr`
starts/resumes them and `<leader>ps` submits them.

## Persistent document and identity

The source of truth is one schema-version 2 document per canonical repository and
branch. It lives under the ignored `.agents/reviews/` directory with a filename derived
from SHA-256 of the identity, so branch names never become unsafe path components:

```text
.agents/reviews/differ-review-v2-<identity-sha256>.json
```

A normal branch identity is `{ "kind": "branch", "name": ... }`; its recorded `head`
is informational and advances without changing the review. A detached checkout uses
`{ "kind": "detached", "commit": ... }`, giving each detached commit a separate
review. The document stores canonical `repository_root`, creation/update timestamps,
and `HEAD` and `main` comparison objects. Each comparison has its spec/base/target and
its own notes.

Every note has a stable ID, body, repository-relative path, old/new source range,
timestamps, `anchor_status`, and `source_context`. Source context records the comparison
and exact source text at capture time: full text for same-side ranges and both endpoints
for cross-side ranges. Rendering requires matching source coordinates and text. Missing
or changed source is marked `outdated` rather
than using Differ's nearest-line fallback and silently displaying the note on unrelated
code. Legacy notes without captured text are `unverified`; older v2 ranges without full
context are also unverified. No fuzzy remapping is done. Evaluated status changes are
saved and refresh open output buffers. Status applies to files/comparisons that have
been opened; unopened files retain their last evaluated status.

The standalone contract is `schemas/differ-review.schema.json`. Runtime validation
rejects malformed documents, unsupported versions, invalid ownership, source points,
and note structures. A rejected existing file puts the session in protected mode: it
can be inspected and reported, but local mutations do not overwrite it.

## Lifecycle and stale-operation protection

Opening a review loads the current identity's document. Closing/reopening Differ and
restarting Neovim therefore resume it. Commits and pushes preserve branch identity;
switching away and back selects the corresponding branch document. Opening a different
repository is independent.

Every save re-reads Git identity. Composer and `vim.ui.select` callbacks also capture
their original session and comparison, then check tab/session, comparison, and branch
again when they complete. A branch switch while a review is open cannot display or save
its notes as the new branch: rendering clears local extmarks and entry points ask the
user to close and reopen. `B` similarly refuses to carry an old session across a branch
change.

Adds, edits, deletes, and reset save the entire branch document. Opening or switching
comparisons never clears notes, but can persist updated anchor status. Cancelling a
composer does not write. Every session retains a fingerprint of the loaded bytes; a
save rejects a changed disk snapshot instead of overwriting newer notes or resurrecting
deleted ones. This is an optimistic conflict check, not a simultaneous-writer lock.
On conflict, preserve any unsaved draft before reopening the review. The writer resolves
real ancestors, rejects symlink escapes and tracked/non-ignored destinations, writes a
private neighboring file through all short writes, fsyncs, and atomically renames it.
Encoding, short-write, or rename failure leaves the prior complete document untouched.

## One-time v1 migration

The legacy `.agents/reviews/differ-review.json` remains byte-for-byte unchanged. When no
v2 document exists, the first opened branch may import a valid schema-version 1 snapshot
into its matching comparison. The v2 migration metadata records the legacy relative
path, version, import time, and a complete `source_snapshot`; migrated notes preserve
their original paths, bodies, ranges, IDs, and timestamps.

After publishing the migrated branch document, the loader writes a small migration claim
and also scans existing v2 documents as a fallback. This prevents the legacy snapshot
from being copied into every branch, even if the first branch document is later damaged.
Reset preserves migration metadata, so it does not re-arm the import. Malformed or
unsupported legacy data is protected and neither the legacy file nor a new v2 destination
is written.

## Review output sidebar

An existing branch JSON appears in a separate **Review output** section. It is appended
after Differ renders its normal `FileEntry` sections and receives dedicated metadata,
not a synthetic `FileEntry`. Therefore Differ's file counts, staging/discard targets,
selection identity, and next/previous-file traversal remain unchanged.

The adaptation is config-local in `lua/config/differ_review_output.lua`: it wraps only
the live panel instance's render callback and chains that panel's `on_refresh`. It does
not modify the installed Differ checkout or monkey-patch the Panel class. `Enter` on the
output opens a read-only JSON scratch split in the review tab; `q` closes only that
split. Open output buffers and the panel refresh after successful saves.

## Tidy, First rationale

The follow-up first extracted branch identity, validation, migration, path confinement,
and atomic persistence into the small `differ_local_review_store.lua` boundary. It then
added the isolated output adapter before changing comment/session integration. That made
the existing in-memory note operations an uncomplicated consumer of one branch document
and kept output routing out of Differ's file model.

This deliberately avoids a generic storage framework, a fuzzy anchor engine, changes to
the installed plugin, and broad class monkey-patches. Differ's composer, anchor helpers,
view rerender hook, and `Panel:select(true)` remain the narrow integration points.

## Verification

Behavioral tests use controlled views, composer/select callbacks, real temporary Git
repositories, and filesystem effects rather than automated key-driving. They cover:

- load/save through a separate Neovim process; repository, branch, detached-commit, and
  comparison separation;
- mutation/reset, v1 source-preserving migration and idempotence;
- stale source context and delayed comparison/branch callbacks;
- malformed/unsupported protection, schema validation, symlink/ignore/tracked guards,
  atomic failures, and partial writes;
- zero GitHub requests and synthetic output exclusion from file routing/counts.

The schema checks use the real Draft 2020-12 validator via `uv` and the pinned PEP 723
helper in `tests/support/validate_json_schema.py`. The full suite and StyLua checks passed.
The canonical temporary directory avoids the baseline macOS `/var` versus `/private/var`
path-alias failure in the existing explorer test.

Manual E2E ran in the separate `differ-branch-e2e` Herdr tab with a disposable two-branch
repository and simulated GitHub backend. Confirmed save gestures, upward visual ranges,
restart/commit persistence, comparison isolation, branch switch/resumption, rejected
stale composer submission, confirmed/cancelled reset, sidebar Enter and directory folds,
read-only JSON opening/closing and refresh after a save, actual clipboard paths, output
exclusion from staging/discard, help, and simulated PR draft/submission. No local
operation called the GitHub backend.

The coordinator also opened this repository's actual review: the saved schema-definition
comment migrated into the current branch document with its body, ID, range, and timestamps
intact. `cmp` against the pre-migration backup confirmed the v1 file was byte-identical,
and the migrated v2 document passed the standalone JSON Schema validator.

Coordinator follow-up kept the same small-boundary approach: replace the bespoke test
schema interpreter with a standard validator, resolve range text from the normalized
source anchor, give the output row a readable label, and label legacy anchors unverified.

The background advisory review reproduced four issues, all accepted: stale sessions
overwriting newer snapshots, incomplete range-context checks, evaluated anchor status
remaining stale in JSON, and runtime validation accepting schema-invalid fields. Focused
fixes added byte fingerprints, range/endpoint context, status publication, and explicit
allowed-key checks at the existing store boundary. No generic merge or validation
framework was introduced. Behavioral regressions cover conflicts (including initially
absent files and deleted notes), invalid documents, range-middle and cross-side changes,
and output-buffer status refresh. The full suite passed after these fixes. Manual follow-up
confirmed a changed range middle persisted as outdated and a real composer save rejected
a newer external snapshot without changing its bytes; local sidecar request count was zero.
The final split-layout pass also confirmed the local marker, `ge` editing, and confirmed
`gx` deletion persisted correctly after reopening the conflicted session.

Run the full suite from `nvim/`:

```sh
TMPDIR=/private/var/folders/p5/zmhxh9795rzd9nn3115zbjb40000gn/T/opencode \
  nvim --headless -u init.lua "+lua require('tests.run').run()" +qa
```

## What to look for in review

- Close/reopen Differ and restart Neovim on two branches; verify each resumes only its
  own `HEAD` and `main...` notes through commits and pushes.
- Switch branches while a composer or note picker is open; verify saving is rejected
  and reopening selects the new branch review.
- Verify the actual v1 file remains unchanged while its note appears once in the current
  branch document, including migration source metadata.
- Verify Review output opens read-only JSON, updates after saves, and never stages,
  discards, changes counts, or participates in `[f`/`]f` navigation.
- Verify `Enter` focuses files and toggles directories in local and GitHub sidebars;
  `c`, `ge`, `gx`, composer save/cancel, `<leader>cr`, `<leader>cR`, `g?`, and ordinary
  `<leader>cp` retain their intended scopes.
