# Continuous Neovim Diff Review

- Once implementation starts, freeze this plan. Record subsequent decisions, deviations, and review points only in `.agents/implementation-notes/nvim-continuous-diff.md`.

## Experience and usage

- `Space gd` opens one continuous inline diff of all changed files; scrolling crosses file boundaries naturally.
- Separate files with full-width, high-contrast header bands, bold repository-relative paths, change counts, and spacing.
- Keep the current file path visible in a sticky window bar; preserve path readability in narrow windows.
- Selecting a file in the sidebar jumps to its header in the continuous view.
- `[` / `]` navigate hunks across files; `[f` / `]f` jump between file sections.
- Start with three context lines; `T` toggles compact/full context without losing position.
- Preserve automatic comparison selection and `B` switching between `HEAD` and the `main` merge-base comparison.
- Keep `gf` source navigation, local comments, saved review output, and GitHub review actions working against the correct file and line.
- Keep `t` available for side-by-side inspection of the current file; returning to continuous view restores the review position.
- Keep `g?` context-aware help and `q` returning to the editor.
- Use one scrolling buffer, asynchronous Git work, bounded rendering batches, and targeted section updates; scrolling must not recompute diffs.
- Apply Tidy, First: isolate single-file assumptions in small preparatory refactors and reuse Differ's existing diff, navigation, and review machinery.

## Verification criteria

- Create a dedicated Herdr tab and manually exercise every workflow below in real Neovim, recording results in implementation notes. Do not replace these manual checks with automated UI scripts.
- Review multiple files end-to-end using scrolling alone; sidebar, file, and hunk jumps land correctly in both directions.
- Manually verify unmistakable file boundaries and readable current-file paths at narrow and wide terminal widths.
- Verify source navigation and comment anchors for additions, deletions, renames, and multiline selections across file boundaries.
- Confirm local notes survive restart and comparison switching; GitHub drafts and submission remain scoped to the correct PR and file.
- Confirm context/layout toggles and refreshes preserve logical position; editing a note or file updates only its affected section or decorations.
- Exercise automatic comparison selection, `B`, `gf`, staging/unstaging, confirmed/cancelled hunk and whole-file discard, help, and closing back to the editor in a disposable repository.
- Exercise local line/range note creation, edit, deletion, reset, outdated anchors, JSON output, path copying, and restart persistence.
- Exercise PR selection, review start/resume, line/range comments, thread replies, composer save/cancel, and review submission using a dedicated test PR; report any unavailable live workflow as blocked.
- Benchmark 10-, 100-, and 1,000-file changesets plus one very large diff; record first-content latency, total load time, memory, and longest UI stall on the same machine.
- Target no main-thread rendering batch over 16 ms and no input stall over 100 ms during scrolling, file jumps, and refreshes; validate with real-terminal interaction and profiling.
- Run existing Neovim review tests and add behavioral coverage for cross-file navigation, anchors, and incremental updates; do not add text-presence tests or automate visual checks assigned to manual verification.
- After checks and tests pass, launch a background advisory reviewer focused on correctness, simplification, and layer boundaries; assess findings and rerun affected checks after accepted fixes.
- Complete implementation notes with explicit user review points, then push the feature branch and create a PR with a short feature-only description.
