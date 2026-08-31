# HTTP Actions API

Base URL: `http://<server.host>:<server.port>/v1`

All routes except `GET /health` require:

```http
Authorization: Bearer <api-token>
Content-Type: application/json
```

The token is stored at `~/Library/Application Support/Macflow/api-token`.
Failures return `{"error":"message"}`.

## Actions

| Method | Path | Input |
| --- | --- | --- |
| `GET` | `/health` | None |
| `GET` | `/permissions` | None |
| `POST` | `/permissions/request` | `{"permission":"accessibility\|screen_recording"}` |
| `GET` | `/applications` | None |
| `POST` | `/applications/launch` | `{"bundle_id":"..."}` |
| `GET` | `/windows?bundle_id=...` | Bundle ID query parameter |
| `GET` | `/windows/<id>` | None |
| `PUT` | `/windows/<id>` | `{"frame":{"x":0,"y":0,"width":800,"height":600}}` |
| `POST` | `/windows/<id>/focus` | None |
| `POST` | `/windows/<id>/unminimize` | None |
| `GET` | `/screens` | None |
| `POST` | `/overlays/image` | `{"path":"...","timeout_seconds":8}` |
| `GET` | `/overlays` | None |
| `DELETE` | `/overlays` | None |
| `POST` | `/file-shelves` | `{"directory":"..."}` plus optional shelf sizing and behavior fields |
| `GET` | `/file-shelves` | None |
| `DELETE` | `/file-shelves/<id>` | None |
| `POST` | `/input/keystroke` | `{"key":"h","modifiers":["cmd","shift"]}` |
| `POST` | `/input/click` | `{"button":"left","x":100,"y":100}` |
| `POST` | `/input/drag` | `{"from":{"x":0,"y":0},"to":{"x":100,"y":100},"duration":0.5}` |
| `POST` | `/screenshots` | Optional `display_id`, `path`, and `show_preview` |

Responses are JSON descriptions of the affected resource or completed action.
Validation failures use `400`, missing resources use `404`, and actions that
cannot be completed use `422`.
