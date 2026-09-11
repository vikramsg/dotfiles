# Implementation notes — macflow A2UI JSON UI

Plan: `.agents/plans/macflow-a2ui-json-ui.md` (frozen; deviations recorded here).

## Decisions not pre-agreed

- **Merged M0–M4 into one change.** The old `FileShelfController`, `WebSurfaceController`,
  and their tests are deleted rather than kept green through an intermediate refactor.
  Keeping a refactor-only milestone for code that is removed in the same PR added
  no value.
- **No `FileDragController` extraction.** The A2UI `FileThumbnail` node reuses the
  existing `FileThumbnailView` directly, so the AppKit drag code did not need to be
  extracted after all.
- **No separate `SurfaceManager` type.** The A2UI surface controller owns the single
  global Escape registration and routes it to the most recently shown surface.
  `SurfaceSession` no longer registers Escape itself.
- **Update semantics implemented as agreed:** `createSurface` resets the surface
  (tree + data model); without it, `updateComponents` upserts by id and
  `updateDataModel` merges at the path.
- **Panel geometry** comes from an optional Macflow `surface` object on
  `createSurface` (`width`, `height`, `margin`, `activates`), defaulting to the
  screenshot-shelf dimensions.
- **`Image` vs `FileThumbnail`:** `Image` remains display-only (basic catalog).
  `FileThumbnail` is a Macflow catalog component; it reuses `FileThumbnailView`,
  so left-click opens, right-click reveals, and drag is native.
- **`SizeHint`/`weight`:** `weight` and finer layout hints are not implemented yet;
  stacks use fixed spacing.

## Deviations from the plan found while implementing

- **`macflow ui show` takes `--file`** (and `-` for stdin), matching the plan.
- **Overlay commands moved** from `ui overlay ...` to a top-level `overlay ...`
  group so `ui` is only the A2UI surface command.
- **`Image` is display-only** (no action); `FileThumbnailView` already provides
  open/reveal/drag, so the `FileThumbnail` node reuses it directly.
- **Not implemented (deliberately):** `weight`, precise `justify` (only
  space-between style is approximated), and scrolling for long `List`s.

## Known limitations to review

- Tab selection resets to the first tab whenever a surface is re-rendered by an
  update, because the node tree is rebuilt.
- `Escape` removes the surface entirely (tree + data), not just hides it.

## Verification performed

- `just --justfile bin/macflow/justfile test`: 89 tests pass (10 core A2UI,
  2 runtime surface-behavior, plus updated CLI/config/theme/runtime suites).
- `just macflow`: release build, signed install, LCH service healthy.
- End-to-end on the running app: listed files with `macflow files list`,
  rendered a tabbed `FileThumbnail` shelf from JSON, verified the frame with
  `macflow screenshot capture` read back through the agent `read` tool, clicked
  the second tab, updated the data model and confirmed a re-render, and
  dismissed with Escape.
- Not automated (manual by policy): the visual frames and the drag-to-Finder drop.

## To review

- Update semantics table and whether `createSurface`-means-reset is the right default.
- `FileThumbnail` reusing `FileThumbnailView` (which hardcodes open/reveal/drag)
  instead of routing through catalog actions.
- Escape routing: most-recently-shown surface wins; confirm that is the desired rule.
- Removal of `surfaces`/`shelves` config and the two hotkeys from `macflow/config.json`.
- Tab-selection reset on re-render, and whether `Escape` should delete the surface
  or merely hide it.

