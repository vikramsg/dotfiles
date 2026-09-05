# Macflow UI workflows

`macflow ui` controls Macflow's own surfaces, not other applications' windows.
Use `macflow window` for those. Presentation settings and configured shortcuts
live in [Macflow configuration](../../../macflow/README.md).

## Image overlays

```bash
macflow ui overlay show /path/to/image.png 8
macflow ui overlay list
macflow ui overlay hide
```

An overlay is a nonactivating image preview. Left click opens the original;
right click reveals it in Finder. A new image replaces the current preview,
and the timeout dismisses it. `list` reports visibility and the image path.

Macflow also watches its screenshot directory: a newly added supported image
produces an automatic preview. Watching existing image files does not require
Screen Recording. Captures made through the CLI suppress that automatic preview
unless `screenshot capture --preview` is requested.

## File shelves

```bash
macflow ui shelf show /path/to/images
macflow ui shelf list
macflow ui shelf close <shelf-id>
```

`show` currently takes a **directory**, not a configured shelf name, and opens
the native shelf. Read the returned ID or use `list` before closing it.
Listing reports visibility, file paths, and its panel frame. That frame uses
AppKit coordinates (bottom-origin); input commands use screen coordinates
(top-origin), so do not pass the shelf frame directly to `input click/drag`.

Configured shelves expose source tabs and show the newest supported files up
to `max_items`. They refresh while visible. A thumbnail drag carries the original
file URL; Macflow does not maintain a separate copy. Escape and completed drags
close the shelf and restore prior focus according to its configuration.

## Native and WebKit

Both implementations remain available through the configured hotkeys. The
checked-in configuration uses Cmd+Shift+H for the native shelf and Cmd+Shift+J
for the WebKit shelf. The CLI does not yet select a configured shelf or WebKit
surface by name. A common renderer-independent command is a roadmap item.

For local WebKit surfaces, HTML/CSS/JavaScript own the content; Macflow owns
panel placement, Escape, focus restoration, theme injection, and native file
dragging. See the [bridge reference](ui-api.md) to write a surface and
[configuration](../../../macflow/README.md) to register its document.
