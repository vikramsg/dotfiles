# Flat commands → command groups

Update scripts to these command paths. Arguments, options, JSON responses,
and HTTP endpoints are unchanged. The old flat command names are not aliases.

| Previous command | Current command |
| --- | --- |
| `health` | `system health` |
| `doctor` | `system doctor` |
| `permissions [request ...]` | `system permissions [request ...]` |
| `applications` | `app list` |
| `launch` | `app launch` |
| `windows` | `window list` |
| `frame` | `window frame` |
| `focus` | `window focus` |
| `unminimize` | `window unminimize` |
| `screens` | `screen list` |
| `keystroke` | `input keystroke` |
| `click` | `input click` |
| `drag` | `input drag` |
| `screenshot` | `screenshot capture` |
| `overlay` | `ui overlay show` |
| `overlays` | `ui overlay list` |
| `hide-overlays` | `ui overlay hide` |
| `shelf` | `ui shelf show` |
| `shelves` | `ui shelf list` |
| `close-shelf` | `ui shelf close` |

Prefix each command with `macflow`. For example:

```bash
macflow screenshot capture --preview
macflow ui shelf show /Users/Shared/Screenshots
macflow system permissions request accessibility
```
