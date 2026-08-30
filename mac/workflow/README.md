# Mac Workflow

`Mac Workflow` is a local, configuration-driven macOS automation service. It
replaces the repository's previous screenshot automation and provides
deterministic application window layouts.

The app is installed at:

```text
~/Applications/Mac Workflow Permissions.app
```

The bootstrap-oriented name is retained because macOS permissions are tied to
its stable identity:

```text
dev.vikramsingh.dotfiles.mac-workflow
```

## Setup

```bash
just mac-workflow
```

This command builds and signs the local app, installs `mac-workflow` under
`~/.local/bin`, links its XDG configuration, installs a login LaunchAgent, and
waits for the app's health endpoint.

The first installation requires Accessibility approval. Screen Recording is
required by `mac-workflow screenshot` and `POST /v1/screenshots`; observing
images written by another capture tool does not require it. Check or request
permissions with:

```bash
mac-workflow permissions
mac-workflow request-accessibility
mac-workflow request-screen-recording
```

## Configuration

The repository file `mac/workflow/config.json` is linked to:

```text
${XDG_CONFIG_HOME:-~/.config}/mac-workflow/config.json
```

Screenshot storage remains independently configured by:

```text
${XDG_CONFIG_HOME:-~/.config}/screenshot/config.json
```

The workflow app reads `screenshot_dir` from that existing file. It never
copies screenshots into its app bundle or application-support directory.

## Shortcuts

```text
cmd + shift + 1  Maximize Ghostty
cmd + shift + 2  Maximize Zed
cmd + shift + 3  Ghostty left, Zed right
cmd + shift + 4  Zed left, Ghostty right
cmd + shift + h  Show the draggable screenshot shelf
cmd + shift + 5  Open the native macOS screenshot controls
```

The native `cmd + shift + 3/4` screenshot shortcuts must remain disabled because
the workflow app owns those keys. Capture through `cmd + shift + 5` instead.

If a configured application has no usable window on the current Space, the app
launches it or sends its standard `cmd + n` new-window shortcut, then waits for
a current-Space window. It does not move an unrelated window from another
Space.

## Screenshot Preview

The app watches the configured screenshot directory for PNG, JPG, JPEG, and
WebP images. A new image produces one nonactivating floating preview on the
screen containing the mouse pointer.

- Left click opens the original image.
- Right click reveals the original image in Finder.
- The configured timeout dismisses the preview.
- A newer image replaces the existing preview.

## Screenshot Shelf

`cmd + shift + h` opens a top-center horizontal shelf populated directly from
the configured screenshot directory, newest first. Dragging a thumbnail starts
a native file drag containing the original file URL, so compatible applications
receive the existing file rather than a copy maintained by Mac Workflow.

Escape closes the shelf. A completed drag closes it after the configured delay.
Both paths restore the application and window that were focused before the
shelf opened.

## HTTP API

The app exposes generic macOS automation primitives at the configured loopback
address. Application-specific names exist only in `config.json`, never in the
HTTP routes.

```text
GET    /v1/health
GET    /v1/permissions
POST   /v1/permissions/accessibility/request
POST   /v1/permissions/screen-recording/request
GET    /v1/applications
POST   /v1/applications/launch
GET    /v1/windows?bundle_id=<bundle-id>
GET    /v1/windows/<id>
PUT    /v1/windows/<id>
POST   /v1/windows/<id>/focus
POST   /v1/windows/<id>/unminimize
GET    /v1/screens
GET    /v1/overlays
POST   /v1/overlays/image
DELETE /v1/overlays
GET    /v1/file-shelves
POST   /v1/file-shelves
DELETE /v1/file-shelves/<id>
POST   /v1/input/keystroke
POST   /v1/input/click
POST   /v1/input/drag
POST   /v1/screenshots
```

Except for health, endpoints require the bearer token stored with mode `0600`
at `~/Library/Application Support/Mac Workflow Permissions/api-token`.

The CLI is a thin HTTP client:

```bash
mac-workflow health
mac-workflow applications
mac-workflow windows com.mitchellh.ghostty
mac-workflow screens
mac-workflow overlay /path/to/image.png
mac-workflow shelf /path/to/images
mac-workflow shelves
mac-workflow close-shelf <id>
mac-workflow keystroke 3 cmd shift
mac-workflow screenshot
mac-workflow screenshot --preview
mac-workflow screenshot --display <display-id>
mac-workflow screenshot --path /Users/Shared/Screenshots/test.png
```

API/CLI captures hide any existing transient overlay and do not create a new
one by default, which keeps automation screenshots clean. Add `--preview` when
the captured image should also use the normal bottom-right preview.

## Tests

```bash
swift test --package-path mac/workflow
```

Implementation decisions and verification results are recorded in
`mac/workflow/IMPLEMENTATION_NOTES.md`.
