# ocost implementation

A standalone Python client for the existing local OpenCode V2 HTTP service.
There is no dependency on ocint and no shared presentation package.

```text
CLI: resolve registration path, capture time, construct dependencies
  -> API: read the supplied registration, authenticate with httpx2
  -> validated overall and project statistics
  -> report -> Rich tables or complete JSON
```

- `cli.py` is the composition root: configuration and time are resolved here.
- `api.py` owns registration parsing, HTTP transport, and safe API errors.
- `models.py` validates consumed fields and preserves extra API data.
- `window.py` calculates shared bounds from an explicitly supplied instant.
- `render.py` owns independent Rich styling, labels, and layout.

From the repository root:

```sh
just --justfile bin/ocost/justfile check
just --justfile bin/ocost/justfile test
just --justfile bin/ocost/justfile build
just ocost
```

Tests exercise observable behaviour with fixture data, injected HTTP transports,
and real CLI subprocesses talking to a temporary localhost server. They do not
contact the user's service, replace application methods, or monkeypatch the
process environment. CLI tests pass their environment to the child process.
Visual quality is checked manually rather than with layout snapshots.

## Excluding projects

Repeat `--exclude-project` to omit projects from terminal and JSON reports. A
selector is an exact project ID, exact canonical path, or a final directory
name that identifies one project uniquely. Unknown or ambiguous selectors fail
without printing a report.

```sh
ocost --exclude-project /work/archive --exclude-project experiments
```

[User guide](../../ocost/README.md) · [Implementation notes](IMPLEMENTATION_NOTES.md)
