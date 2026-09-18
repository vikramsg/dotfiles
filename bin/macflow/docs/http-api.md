# HTTP Actions API

Base URL: `http://<server.host>:<server.port>/v1`

All routes except `GET /health` require:

```http
Authorization: Bearer <api-token>
```

Requests with a JSON body use `Content-Type: application/json`. `POST /v1/ui`
accepts A2UI payloads as `application/a2ui+json` (or any JSON content type).

The token is stored at `~/Library/Application Support/Macflow/api-token`.
Failures return `{"error":"message"}`.

## Service

| Method | Path | Action | Input |
| --- | --- | --- | --- |
| `GET` | `/health` | Report whether Macflow is running. | None |

## Permissions

| Method | Path | Action | Input |
| --- | --- | --- | --- |
| `GET` | `/permissions` | Report current macOS permission states. | None |
| `POST` | `/permissions/request` | Ask macOS for the selected permission. | `{"permission":"accessibility\|screen_recording"}` |

## Hotkeys

| Method | Path | Action | Input |
| --- | --- | --- | --- |
| `GET` | `/hotkeys` | Report whether the global event tap is enabled and whether Secure Input is blocking keyboard events. | None |

Example response:

```json
{
  "event_tap_enabled": true,
  "secure_input_enabled": false
}
```

## Applications

| Method | Path | Action | Input |
| --- | --- | --- | --- |
| `GET` | `/applications` | List running applications. | None |
| `POST` | `/applications/launch` | Launch or activate an application. | `{"bundle_id":"..."}` |

## Windows

| Method | Path | Action | Input |
| --- | --- | --- | --- |
| `GET` | `/windows?bundle_id=...` | List windows for an application. | Bundle ID query parameter |
| `GET` | `/windows/<id>` | Read one window. | None |
| `PUT` | `/windows/<id>` | Move and resize a window. | `{"frame":{"x":0,"y":0,"width":800,"height":600}}` |
| `POST` | `/windows/<id>/focus` | Focus and raise a window. | None |
| `POST` | `/windows/<id>/unminimize` | Restore a minimized window. | None |

## Screens

| Method | Path | Action | Input |
| --- | --- | --- | --- |
| `GET` | `/screens` | List displays and their usable frames. | None |

## Overlays

| Method | Path | Action | Input |
| --- | --- | --- | --- |
| `POST` | `/overlays/image` | Show an image overlay. | `{"path":"...","timeout_seconds":8}` |
| `GET` | `/overlays` | Report the current overlay. | None |
| `DELETE` | `/overlays` | Hide the current overlay. | None |

## UI

| Method | Path | Action | Input |
| --- | --- | --- | --- |
| `POST` | `/ui` | Render or update surfaces from an A2UI payload. | One A2UI message or an array of them |
| `GET` | `/ui` | List surfaces with visibility, frame, and component count. | None |
| `DELETE` | `/ui/<surfaceId>` | Remove a surface. | None |

See [UI workflows](ui.md) for the payload shape and update semantics.

## Files

| Method | Path | Action | Input |
| --- | --- | --- | --- |
| `GET` | `/files?directory=...&extensions=...&limit=...` | List supported files, newest first. | Directory query parameter; extensions and limit optional |

## Input

| Method | Path | Action | Input |
| --- | --- | --- | --- |
| `POST` | `/input/keystroke` | Send a keyboard shortcut. | `{"key":"h","modifiers":["cmd","shift"]}` |
| `POST` | `/input/click` | Click a screen coordinate. | `{"button":"left","x":100,"y":100}` |
| `POST` | `/input/drag` | Drag between screen coordinates. | `{"from":{"x":0,"y":0},"to":{"x":100,"y":100},"duration":0.5}` |

## Screenshots

| Method | Path | Action | Input |
| --- | --- | --- | --- |
| `POST` | `/screenshots` | Capture a display to a PNG file. | Optional `display_id`, `path`, and `show_preview` |

Responses are JSON descriptions of the affected resource or completed action.
Validation failures use `400`, missing resources use `404`, and actions that
cannot be completed use `422`.
