# Macflow Implementation Notes

## 2026-08-31: Themed Multi-Source File Shelf

### Scope

- Added `MacflowUI` as a package target for native presentation code.
- Added the built-in `system` and `tokyo-night` themes.
- Added themed source tabs to file shelves.
- Added live refresh while a shelf is visible.
- Made Macflow own explicit screenshot and shelf directories.
- Added a root `justfile` guard for the independently owned Macflow and
  screenshot configurations.
- Kept the existing HTTP surface unchanged. No generic action, UI, theme, or
  event endpoints were added.

### Configuration Ownership

Macflow no longer reads `screenshot/config.json` at runtime. Its capture path
and shelf source paths are explicit values in `macflow/config.json`.

The screenshot tool continues to own `screenshot/config.json`. Duplication of
`/Users/Shared/Screenshots` is intentional because either tool must be able to
load and operate without the other's configuration file.

The private root recipe `validate-screenshot-directories` enforces the
repository-level invariant that:

```text
macflow .screenshots.directory
macflow .shelves.screenshots.sources[id=local].directory
screenshot .screenshot_dir
```

all have the same value. Remote sources may use a different directory. Both
`just screenshot` and `just macflow` run the
guard before installation.

### UI Boundary

The package dependency direction is:

```text
MacflowCore <- MacflowUI <- Macflow executable
```

Configuration DTOs and automation behavior remain in `MacflowCore`. Theme
resolution, shelf selection state, panels, thumbnails, and overlays live in
`MacflowUI`. Runtime controllers in the executable connect automation services
to the UI target.

This separation was the Tidy, First step. The existing shelf controller mixed
file discovery, lifecycle, rendering, and styling. Moving rendering and theme
state behind `MacflowUI` made tab selection and inherited styling isolated
changes instead of extending that monolith.

### Theme Decisions

`appearance.theme` contains only a built-in theme ID. Tokyo Night is compiled
into Macflow and is not duplicated in user configuration.

Components consume semantic colors from one resolved `MacflowTheme`, including
background, surface, raised surface, selected surface, border, focused border,
primary text, secondary text, muted text, and accent. Shelf panels,
thumbnails, tab labels, tab icons, selected states, empty states, and overlay
borders all use those values.

Tab geometry is also theme-owned. `TabStyle` supplies icon size, icon-to-label
spacing, horizontal padding, control height, vertical padding, minimum width,
inter-tab spacing, and font size. `ShelfTabButton` centers the measured icon and
label as one group and preserves the theme's edge padding when labels must
truncate. It does not use AppKit's default independent image/title layout.

Unknown nonempty theme names pass structural configuration validation but fail
during UI theme resolution with an explicit error. This keeps the core target
independent of the UI theme catalog.

### Shelf Decisions

A shelf has one or more generic sources. Each source owns an ID, label, SF
Symbol name, and explicit directory. The first source is selected initially.
Tabs are hidden for one-source shelves, preserving the compact behavior of the
existing `macflow shelf <directory>` command.

Directory watchers are deduplicated by standardized path. This matters for the
initial local/remote setup because both tabs currently point to the same local
directory. A watcher refreshes the selected source without closing or
recreating the panel. Missing source directories are shown as unavailable and
are not silently created.

The Local VM and Remote VM tabs intentionally both use
`/Users/Shared/Screenshots` for this first implementation. This exercises the
complete tab and theme behavior without making Macflow depend on the screenshot
tool or SSH.

### Behavioral Tests

The test suite contains 65 passing tests. New tests exercise public behavior:

- Configuration decodes explicit shelf and capture directories.
- An omitted appearance selects the system theme.
- Empty theme IDs and duplicate shelf source IDs are rejected.
- Tokyo Night resolves as a dark built-in theme with its defining background
  and accent colors.
- Unknown built-in themes are rejected at the UI boundary.
- Shelf selection starts with the first source, switches to a known source,
  and ignores an unknown source.
- The rendered shelf exposes both configured tabs and selecting the Remote VM
  tab changes the selected source.
- An empty selected source renders an empty state.
- An unavailable selected source renders a distinct failure state.
- The Tokyo Night appearance and root background reach the rendered panel.
- Tab content is centered with at least the theme's horizontal padding.
- Icon size and icon-to-label spacing change when a different theme supplies
  different metrics, proving the component has no embedded spacing values.
- Selection changes appearance without shifting icon or label geometry.
- A preferred-width tab displays the complete configured label without
  truncation.

Tests assert configuration outcomes, visible controls, selection behavior, and
rendered appearance. They do not assert controller call order, private helper
usage, or the complete AppKit subview hierarchy.

### Manual Verification

The signed application was installed through `just macflow` and verified with
granted Accessibility and Screen Recording permissions. LCH reported
`lch-macflow` as loaded and the health endpoint returned the new process ID.

Macflow's existing APIs were used to drive and observe the installed app:

- `macflow keystroke h cmd shift` opened the configured shelf.
- `macflow shelves` reported a visible 1156 by 180 shelf and the five expected
  newest paths.
- `macflow screenshot --path <temporary-path>` captured the rendered shelf
  outside its watched directory.
- Reading `tokyo-night-local.png` confirmed the Tokyo Night panel, Local VM and
  Remote VM tabs, SF Symbols, selected state, labels, and thumbnails.
- `macflow click left 925 58` selected Remote VM.
- Reading `tokyo-night-remote.png` confirmed the selected state moved to the
  Remote VM tab while the shelf remained visible.
- `macflow screenshot` created a new file in `/Users/Shared/Screenshots`.
- Reading `live-refresh.png` confirmed the open selected tab refreshed and
  displayed that file as its newest item.
- `macflow keystroke escape` closed the shelf; `macflow shelves` reported it
  hidden and `macflow applications` reported the previously focused Ghostty
  application active.
- `macflow shelf /Users/Shared/Screenshots` exercised the unchanged one-off
  shelf endpoint. Reading `one-off-shelf.png` confirmed a themed shelf without
  a redundant single-source tab bar.
- `macflow shelf <empty-directory>` retained the existing failure contract and
  returned `No supported files available` instead of opening an empty one-off
  shelf.
- `macflow drag 380 145 800 950 0.8` dragged the original screenshot URL into
  the active application. The shelf closed after the successful drag and the
  original file remained present.
- The configured theme was temporarily changed to `system`, the service was
  restarted, and reading `system-theme.png` confirmed the shelf retained its
  behavior with system colors. The final configuration was restored to
  `tokyo-night` and the service was restarted.
- `just validate-screenshot-directories` succeeded for the final configuration.
  A temporary local source-path mismatch was introduced and the same recipe
  failed with the expected diagnostic before the path was restored. A distinct
  temporary Remote VM path passed, confirming that the guard does not constrain
  future remote configuration.
- Reading `tab-spacing-local-final.png` confirmed that Local VM renders as a
  compact centered icon-label group with balanced pill padding and a complete
  label.
- The Remote VM tab was selected through `macflow click`; reading
  `tab-spacing-remote-final.png` confirmed the same geometry in the opposite
  selection state and verified that the full button remained clickable.

Verification captures are under the OpenCode temporary directory at
`/private/var/folders/p5/zmhxh9795rzd9nn3115zbjb40000gn/T/opencode/macflow-verification/`.

### Remaining Remote Verification

The Remote VM tab is currently backed by the local directory, as requested for
the initial implementation. It proves tab selection and rendering but does not
prove remote transport, remote freshness, failure handling, or drag
materialization.

Before remote support is considered complete, configure the Remote VM source
with its real provider or mirrored directory and repeat the visual, live
refresh, open, reveal, and drag checks against an actual remote VM.

## Previous Review Focus

- Confirm `MacflowCore`, `MacflowUI`, and executable responsibilities are at the
  intended boundaries, especially that the core target has no UI theme
  dependency.
- Confirm the `sources` configuration is general enough for future non-screenshot
  shelves without introducing screenshot-specific behavior into Macflow UI.
- Review the final tab geometry in `tab-spacing-local-final.png` and
  `tab-spacing-remote-final.png`, especially balanced pill padding, compact
  icon-to-label spacing, complete labels, and selected versus unselected states.
- Confirm the root `justfile` is the correct owner of the duplicated screenshot
  directory invariant, that both install recipes should fail on a local-path
  mismatch, and that remote sources remain free to use a different path.
- Review the decision to deduplicate watchers by directory while allowing
  multiple tabs to point at that directory.
- Confirm the one-source HTTP shelf remains visually and behaviorally compatible
  despite now using the shared themed renderer.
- Treat real remote-VM source behavior as intentionally unverified follow-up,
  not as completed functionality.

## 2026-08-31: Configured WebKit Surface Prototype

### Scope

- Added generic local WebKit surfaces configured under `surfaces` in
  `macflow/config.json`.
- Added `show_surface` as a hotkey action and assigned `cmd + shift + j` to the
  checked-in `screenshots-web` surface.
- Kept `cmd + shift + h`, the native shelf, its HTTP API, and one-off shelf
  behavior unchanged.
- Added the user-owned screenshot shelf document under
  `macflow/ui/screenshot-shelf/` rather than bundling it in Macflow.app.
- Added no JavaScriptCore runtime, local web server, or HTTP route.
- Added concise API references under `bin/macflow/docs/` for the existing HTTP
  actions and the new `window.macflow` UI bridge.

### Responsibility Boundary

Macflow interprets these surface fields:

```text
document
width / height / margin
activates
close_after_drag / close_delay
restore_focus
```

The `configuration` object is decoded as generic JSON and passed unchanged to
the page as `window.macflow.configuration`. The screenshot shelf JavaScript,
not Swift, interprets source IDs, labels, icons, directories, extensions,
limits, spacing, and thumbnail width.

The page owns its HTML structure, CSS layout, tabs, polling, loading states,
and DOM events. Macflow owns the native panel, screen placement, focus snapshot,
Escape shortcut, file catalog access, open/reveal operations, and native file
drag session.

### Tidy, First

Before adding WebKit, the panel mechanics were extracted into
`FloatingSurfacePanel` and `SurfaceSession`. The native shelf and WebKit surface
now share panel styling, target-screen placement, Escape registration, and
focus restoration. This made the WebKit experiment additive and kept the
existing shelf controller focused on native shelf state and directory watchers.

Opening either implementation closes the other without restoring focus first,
which also prevents duplicate temporary Escape bindings.

### WebKit Host

`WebSurfacePanel` creates a real `WKWebView` and loads the configured local HTML
with read access limited to that document directory. Main-frame navigation is
limited to files under the same directory. The checked-in screenshot document
also applies a restrictive Content Security Policy.

Macflow injects:

- The opaque surface configuration.
- Semantic theme CSS variables for all native theme colors and radii.
- Promise-based generic file, surface, and diagnostic functions.

Bridge replies remain JSON-compatible Foundation arrays, dictionaries,
strings, numbers, and null values. Unknown actions and malformed payloads fail
with an error rather than dispatching arbitrary native selectors.

### File Images And Dragging

The first live implementation synchronously decoded and re-encoded thumbnails
with `NSImage`. Five large screenshots saturated Macflow's main thread, blocked
the HTTP health endpoint, and allowed overlapping polling requests to queue.
That implementation was removed.

The final implementation returns small file metadata through the script bridge
and serves image bytes through a private `macflow-file:` URL scheme. The scheme
handler accepts only opaque identifiers registered by `files.list`; the page
does not receive a general file URL loader. The page permits only one list
request at a time and avoids rebuilding the DOM when path and modification-date
signatures are unchanged.

WebKit cannot independently create an AppKit file drag with an `NSURL`
pasteboard item. A page pointer-down prepares the file path, and the next native
mouse-drag event starts an `NSDraggingSession` from the WebView. A successful
drop uses the configured close delay and focus restoration behavior.

### Automated Verification

The complete Swift suite has 74 passing tests. Added coverage verifies:

- Surface configuration and opaque nested values decode correctly.
- `show_surface` actions resolve configured surfaces and reject unknown ones.
- Absolute and parent-traversing document paths fail validation.
- Tokyo Night exports semantic WebKit values.
- A real local WebKit test document receives configuration and theme values.
- The test document calls the Promise bridge and receives a nested file-list
  response.
- Quick drag preparation produces the requested file drag, preparation after
  mouse-up cannot arm a later drag, and a subsequent press cannot drag the
  previously prepared file.
- A closed WebKit panel is released after its owning reference is removed.
- Existing native shelf, theme, automation, HTTP, screenshot, and permission
  tests continue to pass.

The package test recipe also executes configuration workflow tests against
temporary files. They prove matching capture/native/WebKit local directories
succeed, each local mismatch fails with the relevant diagnostic, remote paths
remain unconstrained, and an alternate `XDG_CONFIG_HOME` receives both managed
links without writing under the test user's default `.config` directory.

`node --check macflow/ui/screenshot-shelf/app.js`, `jq empty
macflow/config.json`, `just validate-screenshot-directories`, the release build,
and `git diff --check` also pass.

### End-To-End Verification

`just macflow` linked both `config.json` and `macflow/ui`, built and signed the
release app, installed it through LCH, and returned a healthy process. With the
WebKit shelf open, Macflow remained responsive at idle rather than saturating a
CPU as the removed thumbnail implementation did.

The installed application was exercised through its existing automation API:

- `macflow keystroke j cmd shift` opened the 1156 by 180 WebKit shelf.
- `web-shelf-array-final.png` confirmed Tokyo Night styling, balanced Local VM
  and Remote VM tabs, five 220-point cards, filenames, and image content loaded
  through `macflow-file:`.
- `macflow screenshot` created `Screenshot 2026-08-31 at 20.03.41.png` in the
  configured directory. `web-shelf-live-refresh.png` confirmed it became the
  first item without reopening the surface.
- `macflow click left 925 58` selected Remote VM.
  `web-shelf-remote-final.png` confirmed the selected style and unchanged file
  content.
- Left-clicking the first card opened its original path in Preview.
- Right-clicking the first card revealed it and activated Finder.
- `macflow drag 380 145 800 950 0.8` delivered the original file to Ghostty as
  `[Image 1]`; `web-shelf-after-final-drag.png` confirmed the surface closed.
- Escape closed a reopened WebKit shelf and restored Ghostty after both Preview
  and Finder activation tests.
- `cmd + shift + h` still opened the native shelf. `macflow shelves` reported
  its expected frame, five paths, and visible state; Escape returned it to the
  hidden state.
- Editing `app.js` through the live `macflow/ui` symlink and reopening the
  surface changed runtime diagnostics without rebuilding the application,
  proving the document is configuration-owned rather than app-bundled.

Final visual captures and install logs are under:

```text
/private/var/folders/p5/zmhxh9795rzd9nn3115zbjb40000gn/T/opencode/macflow-web-verification/
```

### Limitations

- Local configuration documents are trusted code. They can request generic
  file operations for paths they know; this is not a sandbox for untrusted web
  applications.
- The WebKit shelf polls while visible instead of using the native directory
  watcher. Requests are serialized and unchanged DOM updates are skipped.
- Local and Remote VM still point to the same local directory. No remote
  transport was added or claimed.
- Web surfaces have no new HTTP introspection endpoint; this preserves the
  existing external automation API boundary.

### Review-Driven Hardening

The final pre-PR review identified timing and lifecycle cases not exercised by
the normal-duration manual workflow. They were addressed before publication:

- The panel now records mouse-down and deferred drag events. A late
  `prepareDrag` reply can start the current drag, but a reply arriving after
  mouse-up is discarded instead of arming a stale file for a later gesture.
- Source changes during an in-flight list request mark a reload as pending and
  reject results whose captured source no longer matches the selected source.
- Reopening an activating surface preserves its original focus snapshot.
  Switching between native and WebKit renderers restores that snapshot before
  the next renderer captures focus.
- Top-margin placement is clamped to the visible screen so an extreme but valid
  numeric configuration cannot place the panel entirely off-screen.
- Each file-list refresh replaces the private scheme allowlist while retaining
  stable identifiers for files still present, preventing stale asset mappings
  from accumulating through a long visible session.
- The bridge owns its panel weakly and supplies that panel to capability
  handlers, removing the panel-WebView-bridge-handler retain cycle. A lifecycle
  behavior test verifies release after close.
- The root screenshot-directory guard now includes the WebKit shelf's local
  source while continuing to permit distinct remote paths.
- Macflow configuration linking now honors `XDG_CONFIG_HOME`, matching the
  runtime loader and documentation.

## Review Focus

- Confirm that `surfaces` contains only native host concerns plus an opaque
  configuration object, rather than becoming a JSON component/event language.
- Review the trusted-local-code boundary and whether generic file operations
  need an explicit path allowlist before surfaces are shared outside this
  repository.
- Review `macflow-file:` registration and the choice to serve only files first
  returned by `files.list`.
- Compare `web-shelf-array-final.png` and `web-shelf-remote-final.png` with the
  native shelf, especially card sizing, tab geometry, image quality, and text
  truncation.
- Review the native drag handoff from page pointer-down to AppKit's
  `NSDraggingSession`, including close-after-drop behavior.
- Confirm that 750 ms serialized polling is acceptable for this prototype or
  should become a generic native watch subscription.
- Confirm the shared `SurfaceSession` did not alter native shelf placement,
  Escape handling, or focus restoration.
- Review the behavior-focused drag, panel-release, directory-validation, and
  XDG-linking tests rather than relying on source-shape assertions.
- Treat real remote-VM behavior as unimplemented and unverified.
