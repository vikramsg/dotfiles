# Continuous diff implementation notes

## Agreed scope

- The plan at `.agents/plans/nvim-continuous-diff.md` is frozen as implementation begins.
- Build a changeset-wide inline review with clear file headers and retain existing review workflows.
- Verify behavior with tests and manually in a dedicated Herdr tab; request an advisory background review after checks pass.

## Decisions and review items

### Boundaries and startup

- Tidy, First: separate the changeset view from Git/PR orchestration; reuse Differ's pure renderer, line maps, patch construction, thread boxes, panel, and composer.
- Core implementation was delegated in a background Herdr tab. The coordinator inspected the result, rejected initial performance results, added behavioral coverage, and corrected integration problems found manually.
- Local review opens its own async frontend. Differ's native local frontend synchronously renders the first file, so adopting it afterward cannot meet the opening-latency goal. Removed the superseded native-local adoption branch rather than retaining a compatibility path.
- GitHub reviews retain Differ's native session/sidecar and adopt the continuous view once the PR is available.
- Closing an aggregate for GitHub overview restores the native selector; returning to files creates and adopts a fresh view. Head-move recovery reloads every pinned source and rejects earlier-ref deliveries.
- Compatible native PR extra mappings share one seam in aggregate and inspection buffers. Native edit/zoom callbacks requiring unsupported private editing methods are excluded; `gf` remains the source-editing entry point.
- Corrected explicit `nvim -u <checkout>/init.lua` module precedence. Prepend the selected directory before Lazy starts and retain it with `performance.rtp.reset = false`; appending afterward is insufficient because Lazy caches module search paths. Earlier integrated checks accidentally exercised the default symlinked checkout and were rerun after this fix.
- Use one resolved merge base for both the file list and file contents, including refreshes. No duplicate merge-base lookup is needed.

### Rendering, identity, and editing

- Headers use a full-width contrasting band, bold paths, and staged/unstaged/untracked badges. Badges distinguish two sections for the same partially staged file. Counts trail the path instead of overlaying it in narrow windows.
- The sticky winbar identifies the cursor's file. Side-by-side inspection has explicit OLD/NEW filename bars in the same review tab.
- Aggregate code is unwrapped, with old/new source-line gutters. The local sidebar uses plain filenames; the native PR sidebar retains its file icons.
- Aggregate row lookup is file-aware. Local notes and GitHub threads share a section projection helper, keeping source coordinates file-local while translating reverse lookups into buffer rows.
- GitHub's public thread-rendering entry point dispatches to the aggregate projection for continuous views; native split rendering stays in use. All-file thread anchors remain available for replies and navigation.
- Layout transitions repaint overlays so existing notes/threads appear immediately, and comments made in inspection appear after returning to the aggregate.
- Refresh reuses section objects and cached maps. Unchanged contents do not rerender. Structural changes preserve the selected path/source position; a removed selection lands at its nearest previous index.
- Hunk staging refreshes actual Git sources and carries an index-coordinate action anchor into the destination hunk. Rejected an intermediate frozen-model approach because it still displayed staged content under an unstaged label.
- Async opening, refresh, worker, reconstruction, and painting callbacks are guarded by ownership/generation. Removed sections cannot be painted or resurrected by late results.
- A render remains alive while the aggregate buffer is hidden by inspection. `t` restores the aggregate; `q` closes the whole review.
- `T` opens/closes existing native folds instead of rebuilding every file's fold definitions.
- Whole-file actions share entry-aware staging for both rename paths. Failed staging cannot accidentally execute unstaging through a boolean-expression branch.
- A staged-hunk discard checks that its reverse patch applies to the working file before changing the index. This addresses a real walkthrough failure after formatting changed the worktree. A subsequent concurrent change still produces an explicit partial-outcome diagnostic.
- Source editing is through `gf`; removed the old `df` help entry because that separate native editing action is not bound on the aggregate.

### Performance and deliberate tradeoffs

- Git listing and content reads are asynchronous; revision/index blobs use batched `git cat-file` reads. Worktree reads and preparation use bounded concurrency.
- Small pure renders stay on the main thread. At 5,000 changed rows or 256 KiB of combined source text, the same renderer runs in a libuv worker. The byte threshold also covers large files with sparse changes. No content is truncated.
- Worker results use compact serialized line/map records. Reconstruction and decoration painting yield through deferred approximately 8 ms slices; immediate `vim.schedule` chaining did not yield adequately.
- Yield between model construction and render preparation so their costs do not accumulate in one callback.
- Cursor movement performs no Git calls. Local note rendering skips ownership reads when there are no notes for the updated file.
- PR section completions coalesce overlay repaint requests to one deferred pass per frame; authoritative thread-list replacement still repaints all threads.
- **Source-language syntax highlighting is omitted from these review layouts.** Diff-line and word-level colors remain. This is documented in the user guide and needs explicit review; a whole-buffer syntax pass would reintroduce the measured stall.
- Include the frozen plan in the PR despite the repository's usual plan-file ignore rule, so the implementation can be reviewed against it.

## Verification record

### Build and automated behavior

- Neovim 0.12.5; installed Differ commit `20dc7bbc28eedf3180d9ae3eb6d85506e45b4697` (sidecar 0.1.41).
- Built the real GitHub sidecar with `make go-build`.
- Ran `nvim --headless -u init.lua "+lua require('tests.run').run()" +qa` from `nvim/`, with actual module origin confirmed in this checkout.
- Behavioral coverage includes file-aware source maps, range boundaries, simultaneous local/PR anchors, navigation, incremental updates, status-driven reordering, removed/closed-view results, async open ownership, and failed staged discard preserving the index/worktree.
- Existing tests await asynchronous outcomes rather than assuming immediate rendering. No new wording, styling, screenshot, or scripted manual-walkthrough tests were added.
- StyLua checks and `git diff --check` passed before publication. The final full Neovim suite passed after the advisory fixes.

### Manual Herdr workflows

- Local tab `wE:t3`, pane `wE:p5`, fixture `/tmp/opencode/continuous-review-e2e`.
- Verified continuous scrolling, file/hunk navigation, sidebar selection, header bands, sticky filenames, and narrow (88-column) / wide layouts.
- Verified `T`, `t`, `B`, clean-tree automatic `main` selection, `gf`, refresh, help, and return to the editor.
- Verified hunk stage/unstage, added/deleted/renamed entry staging, cancel/confirm hunk and whole-file discard, and rename restoration.
- Reproduced and fixed whole-file staging moving the cursor to an unrelated file; verified stage → refresh → immediate unstage keeps the same path.
- Verified local line/range notes, both composer save gestures, cancellation, edit, delete, reset/cancel, independent HEAD/main notes, restart persistence, and outdated anchors after editing source.
- Verified the read-only review JSON split and its `q` behavior. Confirmed `Space cr` dispatches the correct absolute path to register `+`; the existing OSC52 paste provider returns the unnamed register rather than reading back the host clipboard.
- PR tab `wE:t4`, pane `wE:p7`, isolated clone `/tmp/opencode/diff-pr-ses-f840ed`.
- Live disposable PR [#344](https://github.com/vikramsg/dotfiles/pull/344): picker, start/resume after restart, line and cross-file range drafts, replies, composer cancellation, split-view comments/replies, verdict cancellation, and submission from inspection.
- GitHub confirmed one `COMMENTED` review and five comments/replies on the intended files. The range remained `review-fixture/b.lua:2–3`. Closed the disposable PR after verification.
- After advisory fixes, verified repeated overview → files transitions, including entering overview from inspection, and native unviewed-file navigation on PR #344 without errors.
- On a fresh local fixture, staged the later hunk, observed its actual `INDEX` source and separate staged/unstaged sections, then immediately unstaged it. The index returned to its prior state and the same hunk remained selected.
- Added direct data-boundary regressions for two out-of-order Git listings, stage/refresh/inverse-action ownership, and intermediate PR-head responses arriving after both final-head sources are rendered.
- The initial `/tmp/opencode/differ-pr-e2e` worktree was adopted by concurrent `ocost` work. Preserved it and moved testing to the isolated clone.
- Loading tab `wE:t5`, pane `wE:p8`: deliberately held later file-read deliveries. Entered inspection with 64/1,000 files loaded, saved a local note, released reads, observed 1,000/1,000 loaded while still in inspection with no errors, then returned to the aggregate with the note intact.
- Opened the 30,002-row large diff in real Neovim; help, context toggle, end-of-buffer jump, and scrolling worked without errors or truncated content.

### Performance evidence

- Rejected the first implementation: 100 files took 5.02 s; 1,000 files timed out after 121 s with a 721 ms event-loop gap.
- Corrected the benchmark to wait for completed decorations as well as text. Readiness polling inspects section state; content is checked once afterward so the benchmark does not repeatedly scan the entire buffer.

| Fixture | First content | Complete | Maximum event-loop gap | Git calls | RSS |
| --- | ---: | ---: | ---: | ---: | ---: |
| 10 files / 830 rows | 111 ms | 115 ms | 31 ms | 7 | 30 MB |
| 100 files / 8,300 rows | 134 ms | 175 ms | 27 ms | 8 | 33 MB |
| 1,000 files / 83,000 rows | 583 ms | 1,208 ms | 79 ms | 22 | 78 MB |
| 20,000-line file / 30,002 diff rows | 256 ms | 307 ms | 40 ms | 7 | 83 MB |

- Manual scrolling/file/hunk navigation dispatched **zero Git calls**, with a recorded maximum gap of approximately 29 ms.
- After the advisory fixes, sequential completed-decoration benchmarks again passed: 1,000 files completed in 1.30 s (95 ms maximum gap), and the large single-file diff in 608 ms (53 ms maximum gap).
- Additional sparse-file stress profiling found model construction and render preparation accumulating in a callback; added a yield between phases. Later timings became inconclusive under shared-host contention (load average 22.6 on four CPUs); an exploratory run reached an 802 ms gap. The table above is the completed benchmark evidence, not a hard real-time guarantee under arbitrary machine load.

## Advisory review

- Launched a separate background reviewer in Herdr (`wE:t6`, pane `wE:p9`) after the full suite and manual workflows passed.
- Accepted concrete PR lifecycle findings: overview re-entry must reconstruct a live aggregate, and moved-head recovery must update every source while rejecting old-ref callbacks.
- Accepted local state findings: successful hunk staging must refresh staged/unstaged sections without changing the user's action target; concurrent Git listings need their own ownership generation.
- Accepted action-map consolidation where native callbacks are supported, and coalescing PR overlay repaint requests. This preserves the existing renderer/session boundaries rather than introducing another framework.
- Accepted removal of a redundant first-hunk render and an unused update wrapper.
- All accepted findings have implementation fixes and passing focused/full-suite checks. Manually repeated overview re-entry and hunk action ownership.
- The targeted background follow-up found the prior findings resolved with no remaining blockers. The coordinator assessed the findings and fixes rather than treating the reviewer as authoritative.

## What you should review

- File boundaries and staged/unstaged badges on your usual terminal width, especially repeated paths and long names.
- The intentional syntax-highlighting tradeoff and `gf` editing workflow.
- The renderer/orchestrator/overlay boundaries and the native GitHub thread-render dispatch.
- Refresh ownership, status transitions, source coordinates, and staged discard behavior with later unstaged edits.
- Explicit `-u` startup behavior and retaining the runtime path instead of Lazy resetting it.
- Responsiveness on your Mac and real large repositories; inspect the measured timings and shared-host contention note above.
