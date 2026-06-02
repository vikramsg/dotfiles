# opencode-state

`opencode-state` is a repo-local `uv` Python CLI for read-only OpenCode SQLite usage and session analytics.

## Install

```bash
uv tool install ./bin/opencode_state --force --no-cache
```

## Safety

- Production database access uses SQLite URI read-only mode (`mode=ro`).
- The tool rejects `:memory:` as an OpenCode DB target.
- Tests and smoke checks should use temporary SQLite databases via `--db` or `OPENCODE_DB`.
- The `query` command only accepts one `SELECT` or `WITH` statement and rejects mutating SQL before execution.

## Usage

```bash
opencode-state config
opencode-state schema
opencode-state summary --days 30
opencode-state summary --days 30 --format json
opencode-state daily --since 2026-01-01 --until 2026-01-31
opencode-state models --days 30
opencode-state sessions --days 30
opencode-state query "select session_id from part limit 5" --format json
```

Path precedence:

- config: `--config`, `OPENCODE_CONFIG`, XDG config path, `~/.config/opencode/opencode.json`, then repo `opencode/opencode.json` fallback when found
- database: `--db`, `OPENCODE_DB`, then the OpenCode data directory default (`opencode.db`)

Relative `OPENCODE_DB` values resolve under the OpenCode data directory.

## Test

```bash
uv run --directory bin/opencode_state pytest
uv run --all-packages --group dev pytest
```
