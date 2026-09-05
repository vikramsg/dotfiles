# OpenCode cost reporting

`ocost` shows OpenCode V2 usage by project and provider/model/variant, with
costs, assistant steps, session counts, and token/cache details in readable tables.

## Install and run

From the repository root:

```sh
just ocost
ocost                  # All time
ocost --days 0         # Today, from local midnight
ocost --days 7         # Last seven rolling 24-hour periods
ocost --days 7 --json  # Complete API responses as JSON
ocost --help
```

Installation requires `uv` and Python 3.14 or newer. The installed executable
lives in uv's tool bin directory (normally `~/.local/bin`), which must be on PATH.
It works outside this repository and does not need `jq`, `ocint`, or an
`opencode2 api` subprocess.

If you previously loaded the zsh helper, remove its in-memory definitions once:

```sh
unfunction ocost _ocost_stats _ocost_totals 2>/dev/null
rehash
whence -v ocost
```

New shells use the executable directly when the old function has been removed
from `.zsh_script`.

## Connection

OpenCode V2 must already be running. The CLI reads its existing registration
from `$XDG_STATE_HOME/opencode/service.json`, falling back to
`~/.local/state/opencode/service.json` when that variable is unset or empty.
It uses the registered local URL and HTTP Basic authentication with username
`opencode` and the registered password. It does not print the password, follow
redirects, use proxy environment variables, or accept a remote registration URL.

The command never starts, restarts, or modifies OpenCode. If the registration
is missing, start OpenCode V2 yourself. For an unavailable service or stale
credentials, inspect `opencode2 service status`.

## What the numbers mean

- Costs come directly from `/api/session/stats`, including its project filter.
  There are no database reads or independently reconstructed accounting rules.
- Every request uses the same `from` and `to` timestamps. Day filtering is sent
  to the statistics API, not applied to lifetime costs of recently updated sessions.
- Projects and their models are ordered by descending cost. Zero-cost usage
  remains visible; projects with no usage are omitted only from terminal output.
- Provider, model, and variant remain distinguishable. Project names expand to
  paths and IDs when needed to distinguish matching names.
- Costs are shown in USD to six decimal places; token counts use digit grouping.
  On narrow terminals, token columns stack with a label beside each value.
- These are OpenCode's reported costs, not a provider billing statement.
  Historical-agent and individual-session breakdowns are not included.
- Requests are separate reads, not an atomic snapshot. If project costs do not
  reconcile with the overall cost, the terminal report displays a warning.
- A failed request is an error, never zero usage. Nothing is printed to stdout
  until the complete report has been fetched and validated.

`--json` retains the overall response's keys, including `data`, and adds a
`projects` array. Each entry contains the full `project` metadata and its `usage`
response, including unused projects. Unknown API fields and unrounded values are
preserved; terminal formatting is not applied to JSON.

See [implementation notes](../bin/ocost/IMPLEMENTATION_NOTES.md) for development,
verification, and review guidance.
