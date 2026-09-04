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
macflow doctor
macflow permissions
macflow permissions request accessibility
macflow permissions request screen-recording
```

`macflow doctor` combines the permission and hotkey status APIs into a concise,
terminal-aware health report. Permission prompts remain available under the
`permissions request` subcommand.

Run `macflow --help` to list every command. Each command and nested subcommand
supports `-h` and `--help`, including:

```bash
macflow doctor --help
macflow permissions --help
macflow permissions request --help
macflow screenshot --help
```

## Configuration

The repository file `macflow/config.json` is linked to:

```text
${XDG_CONFIG_HOME:-~/.config}/macflow/config.json
```

User-owned WebKit documents under `macflow/ui/` are linked to:

```text
${XDG_CONFIG_HOME:-~/.config}/macflow/ui/
```

Screenshot storage remains independently configured by:

```text
${XDG_CONFIG_HOME:-~/.config}/screenshot/config.json
```

Macflow and the screenshot tool each own an explicit screenshot directory.
The root `justfile` validates that the independently configured paths agree
before installing either tool. Macflow never reads the screenshot tool's
configuration at runtime or copies screenshots into its app bundle or
application-support directory.

## Shortcuts

```text
cmd + shift + 1  Maximize Ghostty
cmd + shift + 2  Maximize Zed
cmd + shift + 3  Ghostty left, Zed right
cmd + shift + 4  Zed left, Ghostty right
cmd + shift + h  Show the draggable screenshot shelf
cmd + shift + j  Show the WebKit screenshot shelf prototype
cmd + shift + 5  Open the native macOS screenshot controls
```

Every configured shortcut declares `"scope": "global"`. Macflow consumes these
global chords before macOS or the focused application receives them; shortcuts
that are not configured continue through the normal event path. Capture through
`cmd + shift + 5` while Macflow owns `cmd + shift + 3/4`.

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

`cmd + shift + h` opens a top-center horizontal shelf with one tab per configured
source. Each tab is populated directly from its explicit directory, newest
first, up to the shelf's configured `max_items` limit. The limit defaults to
five when omitted. Macflow watches source directories while the shelf is open
and refreshes the selected tab when files change. Dragging a thumbnail starts a
native file drag containing the original file URL, so compatible applications
receive the existing file rather than a copy maintained by Macflow.

Escape closes the shelf. A completed drag closes it after the configured delay.
Both paths restore the application and window that were focused before the
shelf opened.

`appearance.theme` selects a built-in theme for Macflow-owned UI. The bundled
themes are `system` and `tokyo-night`; user configuration selects a theme by
name and does not redefine its tokens.

## Web Surfaces

A configured surface references a local HTML document relative to the Macflow
configuration directory. Macflow owns its `NSPanel`, placement, focus
restoration, Escape handling, theme injection, and native file drag session.
The referenced HTML, CSS, and JavaScript own structure and interaction.

The surface's `configuration` object is opaque to Macflow and is exposed as
`window.macflow.configuration`. Built-in semantic theme values are available as
CSS custom properties prefixed with `--macflow-`.

The narrow page bridge exposes generic operations:

```text
macflow.files.list(...)
macflow.files.open(path)
macflow.files.reveal(path)
macflow.files.prepareDrag(path)
macflow.surface.dismiss()
```

Images returned by `files.list` use a private `macflow-file:` WebKit scheme.
Only paths registered by the native file listing are served through that
scheme. No local web server, JavaScriptCore runtime, screenshot-specific Swift
API, or new HTTP endpoint is involved.

## HTTP API

See [`docs/api.md`](docs/api.md) for the short API index, the HTTP actions
reference, and the WebKit `window.macflow` contract.

The app exposes generic macOS automation primitives at the configured loopback
address. Application-specific names exist only in `config.json`, never in the
HTTP routes.

```text
GET    /v1/health
GET    /v1/permissions
POST   /v1/permissions/request
GET    /v1/hotkeys
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

Macflow tests use Swift Testing and require Swift 6 or newer.

```bash
just --justfile bin/macflow/justfile test
just --justfile bin/macflow/justfile build
```
