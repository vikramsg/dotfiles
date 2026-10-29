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
- Not implemented (deliberately): `weight`, precise `justify` (only
  space-between style is approximated), and scrolling for long `List`s.
- Only implemented components/functions are accepted by the catalog, so
  unsupported payloads are rejected instead of silently doing nothing.
  `files.drag` was dropped from the catalog: drag is intrinsic to
  `FileThumbnail`, so there is no drag function to invoke.

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

## Advisory review triage

Accepted (fixed):
- `A2UISurfaceStore.apply` is now atomic — it mutates a copy and publishes only
  after every message validates.
- The catalog now lists only implemented components/functions, and `action` is
  rejected on anything but `Button`, so unsupported payloads fail validation
  instead of returning 200 and silently rendering nothing.
- The resolver tracks a visiting set and reports component cycles.
- A negative array index (`/items/-1`) no longer traps.
- The decoder requires `v0.9.1` exactly.

Rejected (advisory only):
- Routing `FileThumbnail` open/reveal through the controller's action dispatch.
  `FileThumbnailView` already implements open/reveal/drag; re-plumbing them
  through callbacks would duplicate its behavior rather than simplify. The
  controller's `handle` and the view both call `NSWorkspace` on the same paths,
  so open/reveal behavior is identical.

## To review

- Update semantics table and whether `createSurface`-means-reset is the right default.
- `FileThumbnail` reusing `FileThumbnailView` (which hardcodes open/reveal/drag)
  instead of routing through catalog actions.
- Escape routing: most-recently-shown surface wins; confirm that is the desired rule.
- Removal of `surfaces`/`shelves` config and the two hotkeys from `macflow/config.json`.
- Tab-selection reset on re-render, and whether `Escape` should delete the surface
  or merely hide it.

