# Macflow

Macflow is a configuration-driven macOS app for window layouts, screenshots,
file listing, and JSON-described UI. Its CLI is an HTTP client for the running
signed app; it never falls back to controlling macOS itself.

## Start here

- **New Mac:** follow the [bootstrap guide](../../macflow/BOOTSTRAP.md).
- **Configure workflows:** see [configuration](../../macflow/README.md).
- **Use the CLI:** start with `macflow --help`, then a command group's `--help`.
- **Something failed:** run `macflow system doctor` and see
  [troubleshooting](docs/troubleshooting.md).

## Commands by responsibility

| Group | Purpose |
| --- | --- |
| `app` | List, launch, and activate applications |
| `window` | Inspect, move, resize, focus, and unminimize windows |
| `screen` | Inspect displays and their usable frames |
| `input` | Send keyboard shortcuts, clicks, and drags |
| `screenshot` | Capture displays to PNG files |
| `files` | List files for building a UI |
| `ui` | Create, inspect, and dismiss JSON-described UI surfaces |
| `overlay` | Show, inspect, and hide image overlays |
| `system` | Inspect service health, permissions, and global shortcuts |

`macflow ui show --file <payload.json>` sends an A2UI payload and Macflow renders
it natively. See [UI workflows](docs/ui.md) and the
[HTTP and UI API index](docs/api.md).

## Install versus update

From the checkout that should own your live configuration:

```bash
just macflow
```

This links configuration, builds and signs `~/Applications/Macflow.app`, installs
`~/.local/bin/macflow`, and registers the `lch-macflow` service. On macOS it also
links the [Macflow skill](skills/macflow/SKILL.md) to `~/.config/opencode/skills/macflow`.
It does not install the skill on other platforms.

The package owns skill linking; the root recipe supplies the destination. To
link only the skill, without changing Macflow configuration or restarting it:

```bash
just --justfile bin/macflow/justfile link-skill "$HOME/.config/opencode/skills/macflow"
```

**Do not run the root installer from a temporary worktree if another checkout
owns your live config.** To build without relinking or restarting anything:

```bash
just --justfile bin/macflow/justfile test
just --justfile bin/macflow/justfile build
```

For a binary-only update, stop the existing LCH job, back up the installed app
and CLI, replace their executables with `.build/release/macflow`, re-sign the
installed bundle, and restart the same job. Do not copy configuration or change
its symlinks. Preserve this designated signing requirement:

```bash
codesign --force --sign - \
  --requirements '=designated => identifier "dev.vikramsingh.dotfiles.mac-workflow"' \
  "$HOME/Applications/Macflow.app"
codesign --verify --deep --strict "$HOME/Applications/Macflow.app"
macflow system doctor
```

Macflow requires macOS 14+ and Swift 6+ to build. Accessibility and Screen
Recording approval belong to the signed app, not the terminal or CLI.

## References

- [HTTP and UI API index](docs/api.md)
- [HTTP reference](docs/http-api.md): authentication, routes, and payloads
- [UI workflows](docs/ui.md): A2UI payloads and commands
- [Roadmap](ROADMAP.md): ideas, not a description of available commands
