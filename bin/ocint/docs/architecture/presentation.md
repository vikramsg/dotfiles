# Presentation architecture

- Services and repositories return typed data and contain no presentation logic or backend imports.
- Feature `render.py` modules own human-readable composition. In particular, `ctx/render.py` composes ctx human output and may return Rich renderables.
- Feature CLIs choose human or machine output, but do not call Click echo functions or Rich directly.
- `cli/_render.py` owns `Console`, TTY behavior, stdout, and stderr. `CliOutput.display(object)` keeps the shared protocol backend-neutral; `write()` preserves exact `click.echo` output.
- Machine JSON, JSONL, CSV, and raw output is exact and unstyled. It always uses `write()`, never `display()`.
- Tests assert typed service/repository boundaries, feature composition semantics, CLI routing, and exact machine output separately. Human tests do not depend on ANSI sequences or decorative borders.
