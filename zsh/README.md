# Zsh helpers

## OpenCode usage

`ocost` in `.zsh_script` shows the usage reported by the OpenCode V2 service:

```sh
ocost                  # Full report, all time
ocost --days 0         # Full report, today since local midnight
ocost --days 7         # Full report, last seven rolling 24-hour periods
ocost --days 7 --json  # The same range as structured JSON
ocost --help
```

Every report includes overall totals, costs by project, and each project's
model breakdown. Project and model details show cost, assistant steps, input,
output, reasoning, cache-read, and cache-write tokens. Project totals also show
root sessions, subagents, and prompts. Projects and their model rows are sorted
by descending cost. Provider, model, and variant remain separate; no view
selection or project/session IDs are needed as input.

The helper requires `opencode2` and `jq`. It uses `/api/project` to discover
projects, then `/api/session/stats` for overall and project-filtered usage through
`opencode2 api`. This uses OpenCode's service discovery and authentication, which
may start its background service if necessary. It does not query SQLite or
recalculate usage from session histories. Historical-agent and individual-session
costs are not included: this report exposes the breakdowns available from the
statistics endpoint.

All statistics requests use the same `from`/`to` timestamps. `--days 0` starts
at local midnight; positive values select rolling 24-hour periods. The filter is
sent to the usage statistics API, not applied to lifetime session costs. Projects
with no sessions, subagents, steps, or cost in that window are omitted from the
terminal report. Zero-cost model usage remains visible. Short project IDs
distinguish separate records sharing the same directory.

Costs are displayed in USD to six decimal places. `--json` preserves the overall
API response under its existing keys (including `data`) and adds a `projects`
array. Each entry contains `project` metadata and its full `usage` API response,
including projects with no usage. Full project IDs and unrounded costs are retained.

All responses are validated before anything is printed. Failed requests are
errors, never empty usage. The requests are separate reads, not an atomic
snapshot, so active usage can change while the report is assembled. The terminal
report warns if project costs do not reconcile to the overall total.

The repo's `.zshrc` loads `~/.zsh_script`. To load a newly added helper in an
existing shell, run this from the repository root:

```sh
source zsh/.zsh_script
```

### Verification

The tests run the actual zsh function with a fake `opencode2` executable and
real `jq`. They cover project/model/token output, sorting, JSON preservation,
shared date bounds, local midnight, empty usage, invalid responses, request
failures, missing dependencies, and argument handling. Validation and rendering
are reused for overall and project statistics to keep their behavior consistent.

```sh
zsh -n zsh/.zsh_script
python3 -m unittest discover -s zsh/tests -v
```
