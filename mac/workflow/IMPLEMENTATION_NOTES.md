# Implementation Notes

## 2026-08-30

- Preserved the previously authorized identity exactly: bundle ID
  `dev.vikramsingh.dotfiles.mac-workflow`, executable
  `MacWorkflowPermissions`, and installation path
  `~/Applications/Mac Workflow Permissions.app`.
- Kept configuration file-based rather than exposing configuration as HTTP.
  The workflow app reads `${XDG_CONFIG_HOME:-~/.config}/mac-workflow/config.json`.
  Screenshot storage remains owned by the existing
  `${XDG_CONFIG_HOME:-~/.config}/screenshot/config.json` file.
- Defined the HTTP boundary as generic macOS primitives. Application-specific
  names and bundle IDs appear only in `config.json`; they do not appear in HTTP
  routes.
- Chose Apple frameworks only (`Network`, Accessibility, AppKit, Carbon) to
  avoid adding a server dependency for a small loopback-only API.
- Added pure core types first for configuration, geometry, and HTTP parsing.
  This applies Tidy, First by making behavior testable without macOS UI state
  before attaching it to the permissioned process.
- The macOS 14 SDK does not publicly export `kAXWindowNumberAttribute`. The
  bridge queries its established Accessibility attribute name,
  `AXWindowNumber`, and falls back to a process-local `pid:index` handle in the
  HTTP API. Handles are intentionally documented as valid only while the
  target application's window list remains unchanged.
- Converted the setup command from a one-shot permission executable to a
  persistent LaunchServices app. Installation now launches the app, waits for
  its real `/v1/health` response, and installs a thin `mac-workflow` CLI.
- Kept the established app name and executable despite their bootstrap-oriented
  `Permissions` suffix because changing them after TCC approval risks losing
  the permission identity.
- The first persistent install exposed an important correction: default ad-hoc
  signing uses the changing code hash as its designated requirement. The
  installer now supplies an explicit stable designated requirement based on the
  immutable bundle identifier, without introducing an Apple account or local
  certificate. Also corrected `NWListener` construction: specifying both a required local
  endpoint and an initializer port returns `EINVAL`; the required endpoint
  alone binds the loopback listener.
- Added a LaunchAgent that invokes the app through LaunchServices at login. It
  does not launch the executable as a terminal child, preserving correct TCC
  attribution. Added generic overlay inspection and deletion endpoints so the
  watcher and timeout lifecycle can be tested without visual assertions.
- Changed LaunchServices startup from `open -gj` to `open -g`. The `-j` option
  starts an application hidden; the watcher still loaded images, but AppKit
  correctly kept its preview panel off screen. Background launch alone does not
  activate the app and still permits a nonactivating panel to become visible.
- Hotkey conflicts are logged per binding rather than aborting app startup. The
  generic HTTP service and screenshot watcher therefore remain available even
  if one shortcut is reserved by another process.
- Window visibility primarily uses `AXWindowNumber` against WindowServer's
  on-screen IDs. Because the attribute is optional, the implementation falls
  back to matching on-screen windows by process and frame rather than treating
  every such window as unavailable.
- Added a generic keyboard-event primitive, corresponding to Hammerspoon's
  `hs.eventtap.keyStroke`. It lets integration tests invoke registered hotkeys
  through the permissioned app without adding layout-specific HTTP routes.
- Live testing showed `NSRunningApplication.activate()` alone did not reliably
  make Zed frontmost on macOS 14. Focus now also sets the application's
  `kAXFrontmostAttribute` before raising and focusing the selected window.
- Added a generic mouse-click primitive, corresponding to Hammerspoon's event
  posting APIs, so left-open and right-reveal overlay behavior can be exercised
  through the same permissioned process during end-to-end tests.
- The initial click test exposed AppKit's inactive-window first-click rule.
  `PreviewImageView` now explicitly accepts the first mouse event so a
  nonactivating panel can open or reveal its file with one click.
- Layout failures are logged and produce the system alert sound. The deprecated
  `NSUserNotification` API was removed; adopting UserNotifications would add a
  separate notification permission prompt solely for rare automation errors.

## Verification

- `swift test --package-path mac/workflow`: seven tests pass for XDG path
  resolution, repository config decoding, HTTP request parsing, gap/ratio
  geometry, screenshot filtering, newest-file selection, and preview aspect
  ratio.
- The installed service listens only on `127.0.0.1:17421`; unauthenticated
  access returns HTTP 401, and its token has mode `0600`.
- Rebuilding and reinstalling after the final Accessibility grant retained the
  grant, confirming the explicit designated requirement is stable.
- `cmd-shift-1` and `cmd-shift-2` produced the exact usable frame
  `{x:0,y:25,width:1680,height:1025}` and focused the configured application.
  Zed was initially absent and was launched automatically.
- `cmd-shift-3` produced Ghostty `{x:0,width:836}` and Zed `{x:844,width:836}`
  with an 8-point gap, then focused Ghostty. Repeating it produced identical
  frames. `cmd-shift-4` reversed those frames and focused Zed.
- Generic HTTP window frame and focus operations were exercised against the
  live Ghostty window and their resulting AX state was read back through HTTP.
- Creating a PNG in `/Users/Shared/Screenshots` caused one visible preview after
  the configured debounce. Ghostty remained frontmost, the preview disappeared
  after eight seconds, and no copy was created outside the source directory.
- A native `/usr/sbin/screencapture` capture written directly to the configured
  directory also triggered the visible preview, validating the complete native
  capture-to-filesystem-to-overlay path without adding capture responsibility
  to the workflow app.
- `cmd-shift-h` displayed the newest screenshot. WindowServer showed one
  preview panel plus the app's status item, confirming previews do not stack.
- A synthetic first left click opened and dismissed the preview while retaining
  the source image. A synthetic right click dismissed it, activated Finder, and
  retained the source image.
- FlowVision was removed from the Brewfile and uninstalled from `/Applications`.
- Hammerspoon was also removed from the Brewfile and uninstalled after the
  native app passed the same window-layout and screenshot-overlay acceptance
  checks.

## Screenshot Capture

- Added `POST /v1/screenshots` as a generic display-capture primitive and a
  matching thin `mac-workflow screenshot` client. The endpoint accepts optional
  `display_id` and `path` values; neither route nor implementation contains
  workflow-specific application names.
- Chose macOS 14 ScreenCaptureKit (`SCShareableContent` and
  `SCScreenshotManager`) rather than the deprecated CoreGraphics screenshot
  API. PNG encoding uses ImageIO directly into the requested destination.

## Focused Review

- Accepted a high-severity parser finding: malformed, overflowing, or oversized
  `Content-Length` values are now rejected before range arithmetic or request
  authentication. Deterministic regression tests cover negative, `Int.max`,
  oversized, and nonnumeric values.
- Accepted a concurrent-capture finding: generated paths are reserved through a
  small locked allocator until encoding completes, preventing same-second
  requests from selecting the same file. A concurrent deterministic test covers
  ten reservations.
- Accepted an installer race finding: setup now boots out the LaunchAgent,
  terminates the app, and waits with a bound before replacing its executable.
- Accepted an unbounded-retry finding: an unchanged unreadable screenshot is
  retried at most three times; changed metadata resets the retry state.
- Accepted the documentation correction that Screen Recording is now required
  for the new capture primitive.
- Rejected no findings. The reviewer stayed within concrete current behavior
  and proposed no framework expansion or speculative compatibility work.
- A final review pass found two suppression edge cases. Suppression now records
  a pre-existing file's modification date and is consumed only by a newer
  version, so an intervening scan cannot expose an overwrite. Suppression is
  also ignored for paths outside the watched directory, preventing unreachable
  entries from accumulating. Deterministic tests cover both boundaries.

## Native File Shelf

- Migrated hotkeys to a finite action configuration. Swift dispatches only
  `apply_layout` and `show_file_shelf`; application aliases, bundle IDs, layout
  names, shelf names, and key assignments live in the XDG-managed JSON file.
- Added `AutomationRuntime` as the composition root. Application lifecycle,
  AX windows, screens, path watching, capture, transient overlays, and file
  shelves remain separate native services.
- Added `FileCatalog` for direct, newest-first enumeration of supported regular
  files. It has no database, persistent cache, or copied thumbnail files.
- Added a top-center nonactivating `FileShelfPanel` with a horizontal scroll
  view. Each `FileThumbnailView` starts an `NSDraggingSession` whose pasteboard
  writer is the original file URL.
- The shelf registers an unmodified Escape hotkey only while visible. Escape
  and successful drag completion close the shelf and restore the previously
  focused AX window when configured.
- Restored `cmd-shift-h` to the shelf behavior rather than using it as an alias
  for the transient latest-image preview. Automatic bottom-right previews remain
  a separate filesystem-triggered controller.
- Added generic file-shelf and drag HTTP primitives for inspection and testing;
  no route contains a configured shelf or application name.
- The final configuration decodes and validates finite action types, layout
  references, application aliases, ratios, and shelf dimensions before runtime
  services start. Sixteen deterministic tests now cover configuration, action
  lookup, file filtering/sorting, geometry, capture planning, suppression, and
  HTTP framing.

## File Shelf Verification

- `cmd-shift-h` displayed a 1200 by 420 nonactivating panel at the configured
  top-center position. A screenshot captured through the API and inspected with
  the workspace `read` tool showed a horizontal newest-first thumbnail row.
- Escape removed the shelf and left Ghostty frontmost.
- A native drag from the first thumbnail into a real Finder directory completed
  with a copy operation. Finder received a file with the original basename, the
  source remained in `/Users/Shared/Screenshots`, the shelf closed after its
  configured delay, and Ghostty focus was restored.
- A rejected drop into Zed returned `NSDragOperation.none` and correctly left
  the shelf open, demonstrating that close-after-drag only runs on an accepted
  destination.
- Rejected a review finding that claimed `NSView.hitTest` receives points in the
  receiver's local coordinates. A live drag from the second thumbnail failed
  after applying that suggestion because AppKit supplies the point in the
  superview coordinate system. Restoring `convert(_:from: superview)` made
  non-first thumbnails reachable again; the misleading pure geometry test was
  removed because it did not exercise AppKit behavior.
- Generic `POST`, `GET`, and `DELETE /v1/file-shelves` operations were exercised
  through the CLI; the returned state matched the visible panel and direct
  filesystem contents.
- All four configuration-driven layout hotkeys were rerun after the runtime
  refactor and retained their exact frames and focus behavior.
- API captures without `--preview` hide the transient image overlay while
  leaving the file shelf visible for visual inspection. WindowServer inspection
  confirmed no Mac Workflow overlay window remained after capture.

## Shelf Review

- Accepted the drag-duration finding. Generic drag requests now reject
  non-finite, negative, and over-60-second durations before converting to the
  microsecond delay used by synthetic events.
- Accepted the loopback-validation finding. Configuration startup now rejects
  server hosts other than `127.0.0.1`, `::1`, or `localhost`.
- Accepted the token-mode finding. Runtime startup reapplies mode `0600` to both
  existing and newly generated bearer-token files.
- Accepted the replaced-directory watcher finding. The generic path watcher now
  reopens its descriptor after rename/delete events; a temporary-directory test
  verifies a write after replacement is observed.
- Rejected the reviewer's local-coordinate `hitTest` change after live testing
  showed it broke dragging every thumbnail after the first. AppKit supplies the
  point in the receiver's superview coordinate system for this override. The
  restored conversion passed a real second-thumbnail drag into Finder.
- Accepted the duplicate explicit-preview finding by suppressing the watcher
  event for every API capture and explicitly showing the completed image only
  for `--preview`.
- Accepted the overlapping-capture finding by replacing the Boolean preview
  suspension with a reference-counted gate.
- Accepted the hard-coded key finding. A shared key-code resolver now supports
  the normal alphanumeric/punctuation/navigation vocabulary used by config and
  the generic input API, and configuration rejects unsupported keys/modifiers.
- A follow-up review found two request-client edge cases. Empty query keys are
  now skipped instead of indexing an empty split result, and the CLI brackets
  IPv6 loopback hosts when constructing URLs. Deterministic tests cover both.
- Final review reported no remaining must-fix findings. The final suite contains
  24 deterministic tests, including real temporary-directory replacement for
  the path watcher, token permission repair, config validation, generic key
  resolution, concurrent capture allocation, and HTTP framing edge cases.
- Final live verification also covered a second (non-first) thumbnail drag into
  Finder after restoring AppKit's required coordinate conversion. The copied
  file appeared at the drop destination, the source remained in place, the
  shelf closed, and Ghostty regained focus.
- Visual inspection found that an already queued path-watcher callback could
  recreate a transient overlay after the capture endpoint hid it. Automatic
  preview presentation is now suspended for the duration of API capture. It is
  resumed afterward, and `--preview` explicitly displays the completed image.
- A later `read` inspection showed that AppKit's panel state can become hidden
  before WindowServer removes its last composited frame. Capture now waits the
  configured `capture_settle_seconds` after hiding overlays before invoking
  ScreenCaptureKit.
- When no path is supplied, captures are named in the screenshot directory read
  from the existing XDG screenshot config. No second copy or history store is
  created.
- Removed the FlowVision-specific Hammerspoon implementation, test, setup
  recipe, documentation, and Homebrew declaration. Root setup now installs the
  native workflow app instead. After successful native end-to-end verification,
  removed the now-unused Hammerspoon Homebrew declaration as well.
