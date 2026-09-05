# Action workflows

The signed Macflow app performs all macOS operations. Commands return JSON,
except `system doctor`, which prints a readable health report. Errors are
written to stderr with a nonzero exit status.

## Check access first

```bash
macflow system health
macflow system doctor
macflow system permissions
```

Health only reports liveness. Doctor also checks Accessibility, Screen Recording,
the global shortcut listener, and Secure Input. Request missing permissions
only when you intend to show a macOS permission prompt:

```bash
macflow system permissions request accessibility
macflow system permissions request screen-recording
```

If hotkeys cannot start, the HTTP API remains available for diagnostics and
permission requests. After approving access, restart Macflow and run doctor.

## Position a window

```bash
macflow app list
macflow app launch com.mitchellh.ghostty
macflow window list com.mitchellh.ghostty
macflow screen list
macflow window frame <window-id> 0 25 800 600
macflow window focus <window-id>
macflow window list com.mitchellh.ghostty
```

Use the returned display geometry and a freshly listed window ID, not the
example coordinates or a saved ID. Launch may activate an application; focus
raises its window and changes the active application. Window control requires
Accessibility. Re-list windows to verify the resulting frame.

Configured layouts are still invoked through their hotkeys. If a participant
has no usable current-Space window, Macflow launches it or sends Cmd+N and waits
for one; it does not move an unrelated window from another Space. There is no
`layout apply` CLI command yet.

## Capture without showing UI

```bash
macflow screenshot capture --path /path/to/capture.png
macflow screenshot capture --preview
```

Capture requires Screen Recording. It hides any transient image overlay before
capturing, excludes that overlay, and writes a PNG. No new preview is shown
unless requested. The default destination is the configured screenshot directory;
use `--path` for a specific destination and `--display` for a listed display ID.

Inspect the returned path and dimensions, and open the file when visual
verification is needed. `--preview` composes capture with the standard image
preview; it is not required for capture to work.

## Send input

```bash
macflow input keystroke h cmd shift
macflow input click left 100 200
macflow input drag 100 200 500 400 0.5
```

Input requires Accessibility and affects the current desktop. Inspect the
target and its coordinates first. A drag response acknowledges dispatch, not
completion: verify the destination received the file or gesture before continuing.
