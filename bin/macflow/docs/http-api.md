# HTTP Actions API

Base URL: `http://<server.host>:<server.port>/v1`

All routes except `GET /health` require:

```http
Authorization: Bearer <api-token>
```

Requests with a JSON body also require `Content-Type: application/json`.

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

## File Shelves

| Method | Path | Action | Input |
| --- | --- | --- | --- |
| `POST` | `/file-shelves` | Show a shelf for a directory. | `{"directory":"..."}` plus optional sizing and behavior fields |
| `GET` | `/file-shelves` | Report the current native shelf. | None |
| `DELETE` | `/file-shelves/<id>` | Close the identified shelf. | None |

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
