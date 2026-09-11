# Macflow UI workflows

`macflow ui` creates natively rendered surfaces from a JSON payload using the
A2UI protocol. The caller owns the payload; Macflow owns the rendering.

## Show, list, and dismiss

```bash
macflow ui show --file shelf.json   # render a payload
macflow ui show --file -            # read the payload from stdin
macflow ui list                     # surface id, visibility, frame, component count
macflow ui dismiss <surface-id>     # remove a surface
```

Escape dismisses the most recently shown surface. A completed file drag also
dismisses the surface that started it.

## Payload

A payload is one A2UI message or an array of messages. The supported message
types are `createSurface`, `updateComponents`, `updateDataModel`, and
`deleteSurface`. `POST /v1/ui` accepts the same body as `macflow ui show`.

```jsonc
[
  { "version": "v0.9.1",
    "createSurface": {
      "surfaceId": "screenshots",
      "catalogId": "macflow/v1",
      "surface": { "width": 1255, "height": 250, "margin": 12 }
    } },
  { "version": "v0.9.1",
    "updateComponents": { "surfaceId": "screenshots", "components": [
      { "id": "root", "component": "List", "direction": "horizontal",
        "children": { "componentId": "thumb", "path": "/shots" } },
      { "id": "thumb", "component": "FileThumbnail", "url": { "path": "url" } }
    ] } },
  { "version": "v0.9.1",
    "updateDataModel": { "surfaceId": "screenshots", "path": "/shots", "value": [
      { "url": "file:///Users/Shared/Screenshots/a.png" }
    ] } }
]
```

`surface` is optional and sets the panel size, placement margin, and whether it
activates (`width`, `height`, `margin`, `activates`). The `surfaceId` and data
model are scoped per surface.

### Update semantics

| Payload contains | Effect on an existing `surfaceId` |
| --- | --- |
| `createSurface` | Reset: discard the tree and data model, then apply. Re-sending a payload is idempotent. |
| `updateComponents` (no `createSurface`) | Merge: upsert components by `id`. |
| `updateDataModel` | Merge at `path`; `"/"` replaces the whole model. |
| `deleteSurface` | Remove the surface and its data. |

Rendering starts at `root`, so components no longer reachable from the new
`root` are not shown even if still stored.

## Components

The basic A2UI catalog is supported for `Row`, `Column`, `List`, `Text`,
`Image`, `Button`, `Card`, `Divider`, and `Tabs`. Macflow adds `FileThumbnail`,
which renders a thumbnail and provides native file behavior: left-click opens,
right-click reveals, and dragging starts a real file drag.

Actions use `functionCall` or `event`. Local functions are `files.open`,
`files.reveal`, `files.drag`, `surface.dismiss`, and the built-in `openUrl`.

## Files

```bash
macflow files list <directory> [--extensions png,jpg] [--limit 5]
```

`files` returns `name`, `path`, `url`, and `modifiedAt`, newest first. Use it to
build the data model a surface binds to.

## Image overlays

```bash
macflow overlay show /path/to/image.png 8
macflow overlay list
macflow overlay hide
```

An overlay is a nonactivating image preview. Left click opens the original;
right click reveals it in Finder. A new image replaces the current preview, and
the timeout dismisses it.
