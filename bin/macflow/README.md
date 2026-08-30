# Macflow

`Macflow` is a local, configuration-driven macOS automation service. It
replaces the repository's previous screenshot automation and provides
deterministic application window layouts.

The app is installed at:

```text
~/Applications/Macflow.app
```

The existing bundle identifier is retained because macOS permissions are tied
to its stable identity:

```text
dev.vikramsingh.dotfiles.mac-workflow
```

## Setup

```bash
just macflow
```

The root recipe links the XDG configuration and delegates to
`bin/macflow/justfile`. The package recipe builds and signs the app, installs
`macflow` under `~/.local/bin`, registers the `lch-macflow` service through LCH,
and waits for the app's health endpoint.

The first installation requires Accessibility approval. Screen Recording is
required by `macflow screenshot` and `POST /v1/screenshots`; observing
images written by another capture tool does not require it. Check or request
permissions with:

```bash
macflow permissions
macflow request-permission accessibility
macflow request-permission screen-recording
```

## Configuration

The repository file `macflow/config.json` is linked to:

```text
${XDG_CONFIG_HOME:-~/.config}/macflow/config.json
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
POST   /v1/permissions/request
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
at `~/Library/Application Support/Macflow/api-token`.

The CLI is a thin HTTP client:

```bash
macflow health
macflow applications
macflow windows com.mitchellh.ghostty
macflow screens
macflow overlay /path/to/image.png
macflow shelf /path/to/images
macflow shelves
macflow close-shelf <id>
macflow keystroke 3 cmd shift
macflow screenshot
macflow screenshot --preview
macflow screenshot --display <display-id>
macflow screenshot --path /Users/Shared/Screenshots/test.png
```

API/CLI captures hide any existing transient overlay and do not create a new
one by default, which keeps automation screenshots clean. Add `--preview` when
the captured image should also use the normal bottom-right preview.

## Tests

```bash
swift test --package-path bin/macflow
```

Implementation decisions and verification results are recorded in
`bin/macflow/IMPLEMENTATION_NOTES.md`.
