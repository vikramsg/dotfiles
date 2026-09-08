# Continuous Diff Revision — Implementation Notes

## Status and agreed requirements

- Revision implementation has started. The plan at `.agents/plans/nvim-continuous-diff-revision.md` is now frozen; record subsequent decisions and deviations here.
- Retain as much native Differ behavior as possible and reduce duplicated view, source, staging, and PR lifecycle responsibilities.
- Syntax highlighting is required in both continuous and side-by-side review.
- Performance verification covers 10- and 100-file changesets and large dense/sparse single-file diffs with syntax enabled. The user removed the 1,000-file benchmark requirement before implementation.
- Only behavioral tests may be added. Manual verification must not be replaced or duplicated by automated UI scripts.
- Prefer background implementation/review agents and inspect their output before acceptance. Launch the advisory reviewer only after checks and tests pass.
- Complete checks, end-to-end verification, and advisory fixes before pushing and publishing the PR. Its description must contain only short feature-summary bullets reflecting delivered behavior.

## Decisions requiring agreement or review

- Dependency delivery decision: retain upstream Differ at commit `20dc7bbc28eedf3180d9ae3eb6d85506e45b4697` and deliver a reviewable patch in `nvim/patches/differ-continuous-sections.patch`, applied by Lazy's build hook. This avoids copying the plugin into this repository or depending on unrecorded installed-file edits. Review the patch and build/update behavior explicitly.
- The first reusable syntax extension separates native source capture/projection from painting (`collect`, `paint`, section clearing), retaining the same language resolution and highlight queries. Async collection runs in bounded headless Neovim workers with the parent's runtime paths so native Tree-sitter APIs remain available. Worker results and extmark painting are processed in bounded batches; native inspection uses the same async syntax path.
- The coordinator rejected merely replacing split windows while keeping all duplicated local-source logic. The audit is extending native source operations so the changeset controller can reuse Git discovery/content/model behavior asynchronously. Record the final extracted APIs and remaining custom responsibilities after inspecting the delivered code.
- Reuse audit result: native `differ.view` now owns split rendering/windows/editing; native `git.list_async`/`model_async` call the existing source APIs; `git.set_staged` exposes existing whole-file path ownership; native `pr.load_model` shares pinned-ref/model/cache logic; native thread rendering accepts per-file view projections. Removed the repository thread monkey patch and local Git listing/blob-reading/model construction. Native render preparation and bounded diff painting are also shared APIs.
- Remaining custom responsibilities are aggregate indexing/headers, cross-file navigation, logical-position and generation ownership, section reconciliation, repository comparison policy, and local notes. Hunk action retargeting and per-section staging state remain changeset-specific; native patch construction/application and whole-file mutation are reused. Review this remaining boundary rather than assuming all custom code is necessary.
- Performance correction: first coalesced syntax painting into one budget shared across files and removed exact duplicate captures while retaining the last identical capture's precedence. Repeated measurements still found expensive permanent-extmark calls, so native viewport decoration now paints prepared source-derived captures. Scrolling uses this cache and never triggers source parsing/Git.
- Simplified the viewport cache further: Differ's collector sorts by row while preserving within-row capture precedence, in the worker. The editor retains compact capture records and binary-searches visible rows, avoiding another main-thread per-row indexing pass and duplicate row tables. No global garbage-collector policy changes are retained. Review the compact record/serialization boundary and precedence preservation.
- Apply Tidy, First during the architecture audit: identify reusable Differ operations and any small preparatory changes before extending multi-file behavior. Record the chosen boundary and any dependency/API changes before implementing them.

## Verification and advisory findings

- Baseline full suite passed before revision changes, using `nvim --headless -u init.lua "+lua require('tests.run').run()" +qa` from this checkout's `nvim/` directory.
- Lua, Python, and TypeScript parsers and highlight queries are installed. Created syntax-enabled fixtures under `/tmp/opencode/differ-revision-f840/`: 10/100 mixed-language files with multiline source context, and 10,000-line dense/sparse Lua files. Disposable local workflow fixture: `/tmp/opencode/differ-revision-local-f840`.
- Native Differ baseline (one file, model construction plus native stacked View creation/open; Git reads excluded): small Lua file 36 ms total / 25 ms syntax; dense Lua file 1,998 ms total / 1,893 ms syntax; sparse Lua file 1,874 ms total / 1,828 ms syntax. Large cases created 160,030 syntax extmarks. This measures an actual native syntax bottleneck; it does not justify omitting syntax.
- Dedicated manual Herdr tab `wE:t9`, pane `wE:pD`; background implementation tab `wE:t8`, pane `wE:pC`. Agent output and changes require coordinator inspection before acceptance.
- PR #346 remains open; publish the verified revision to that feature PR with an updated feature-only description.
- Full revision test suite, repository Lua formatting, and whitespace checks passed. Applied the final extension to a pristine checkout of the pinned Differ revision; its modules load and `make go-build` succeeds. The advisory review follows these checks.
- New syntax tests passed for native source projection, deleted multiline-string context, Lua/Python section isolation, and stale/empty syntax results. Adapted the existing out-of-order Git listing test to the native asynchronous source boundary, and narrowed the comparison-selection mock to its own Git request so unrelated syntax workers do not corrupt its request count.
- Manual local walkthrough exercised source syntax, native split inspection, `T`/`t`, `gf`, native `df` editing, `B`, line/range note creation, editing, cancellation/deletion, cross-file notes, source editing/outdated anchors, read-only JSON output and clipboard dispatch, hunk stage→fresh INDEX→unstage, and cancelled/confirmed hunk/whole-file discard. Final viewport syntax and remaining restart/reset/loading checks will be repeated after completion.
- Reopened disposable PR #344 for live revision verification. Confirmed picker, draft start/resume after Neovim restart, inline comment on `review-fixture/a.lua:2`, range on `review-fixture/b.lua:1–2`, reply from native split, composer/verdict cancellation, native overview→files round trip, and successful COMMENTED submission. GitHub API confirmed the range and reply ownership. Closed PR #344 again afterward.
- Intermediate permanent-mark benchmarks did NOT consistently pass: 100 files ranged from 5.65–13.06 s with gaps up to 165 ms; a sparse-file run had a 103 ms single painting call. A passing sample alone was not accepted. Final viewport-cache measurements will supersede these as acceptance evidence while retaining this record.
- Final viewport syntax was manually observed in Lua, Python, and TypeScript, including multiline strings and both diff source sides. Native split inspection and return retain syntax. With 4/100 models delivered, entered native inspection and saved a note, then released delayed model results: 100/100 loaded while inspection remained open, with no errors. Scrolling/file/hunk navigation afterward produced zero Git calls and zero syntax-collection calls.
- Restarted local review and observed persistent notes. Confirmed outdated anchors after source editing, read-only JSON, correct clipboard path dispatch, and reset cancellation/confirmation. The live PR test was verified against GitHub's recorded comments/review, not only local display.

### Performance record

- Profile completion waits for source loading, diff preparation, syntax collection, and cache installation; visible syntax is then rendered by the decoration provider. `syntax.get_marks` inspects prepared captures after timing ends. Permanent-extmark counts are no longer a valid completion measure.
- Representative viewport measurements: 10 files completed in 1.43 s (164 ms first content, 26 ms maximum event-loop gap, 4.8 ms maximum deferred callback); 100 files completed in 4.89 s (208 ms first content, 42 ms gap, 10.9 ms deferred callback). Warm unchanged refreshes retained the syntax cache (277 ms / 1.51 s respectively).
- Further compact-record/sorted-cache runs: dense 10,000-line Lua completed in 3.87 s (274 ms first content, 120,015 prepared captures, 87 ms gap, 14.7 ms deferred callback); 100 files completed in 5.92 s (311 ms first content, 69,138 captures, 66 ms gap, 26.8 ms deferred callback). These retain complete syntax and substantially reduce permanent-extmark memory pressure.
- The 16 ms batch target is not a universal measured bound: callback outliers remain in repeated shared-VM runs. Earlier viewport samples also had a roughly 100 ms event-loop gap. Record these as timing variability, not proof that every callback/input meets a hard real-time deadline. Event-loop gaps are a responsiveness proxy and are not identical to externally measured input-to-redraw latency.
- No 1,000-file benchmark was run. Native single-file baselines and all revision fixtures use installed parsers and actual code. Worker Git subprocesses are excluded from the profiler's main-process Git-call counter; zero-call scrolling was separately checked after loading settled.
- RSS figures measure the editor process, not combined worker-process peak memory. Callback wall-time measurements include shared-host scheduling; they are reported without claiming a universal 16 ms bound.

### Advisory review

- Background reviewer launched only after the full functional suite, formatting, whitespace, and reproducible dependency checks passed. Its findings remain advisory; record accepted/rejected findings and affected rechecks here.
- The first review terminal crashed before reviewing due to an environment file-watcher limit. Re-ran the advisory review in a fresh background agent session.
- Rejected the reported missing split `T` binding after checking its actual owner: `git_review.lua` installs the shared context mapping on Differ buffers. Manually verified the binding in native inspection, opened both columns' folds with `T`, then closed both from the other column. No duplicate mapping was added.
- Addressed staged patch whitespace checking: the flagged lines were required single-space prefixes for empty *context* lines in a unified diff, not whitespace added to dependency source. Added a patch-only Git whitespace attribute and separately validate the applied dependency's whitespace; stripping these prefixes would corrupt the patch format.
- Reviewer found no other concrete correctness issue in syntax ownership, worker protocol, native inspection restoration, or pinned build lifecycle.
- Final manual check used the sorted viewport cache with long paths/lines and an approximately 80-column terminal; sticky path, file bands, source colors, and help remained usable. Verified `T` in each native inspection column and restoration to continuous review. The full functional suite passed on this implementation.

## What you should specifically review

- Whether the revised architecture genuinely removes duplicated Differ responsibilities and keeps repository-specific policy in the configuration layer.
- The pinned upstream extension and its build hook in `nvim/init.lua`; inspect `nvim/patches/differ-continuous-sections.patch` alongside the applied Differ source, including the separate worker and viewport-cache APIs.
- Syntax correctness across languages, old/new versions, section updates, and both layouts.
- Capture precedence, compact worker records, per-section cache clearing, and dynamic row offsets when an earlier file grows. Source highlighting is required and is not disabled for large files.
- Navigation, editing, stage/unstage/discard targeting, notes, and GitHub review ownership through refresh and lifecycle transitions.
- Performance evidence with syntax enabled, including any missed targets or unresolved bottlenecks.
- The remaining changeset-specific hunk retargeting/state in `differ_continuous_review.lua`; source reads, models, whole-file ownership, native inspection, and PR thread rendering are now shared with Differ.
- Every additional decision recorded above. Expand this checklist with concrete files and implementation-specific review points before publication.
