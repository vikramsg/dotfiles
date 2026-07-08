# ocint

`ocint` is a standalone UV package for read-only OpenCode SQLite inspection.

It exposes exactly one console script:

```bash
ocint
```

Command groups:

- `ocint state ...` provides OpenCode usage analytics under the new prefix.
- `ocint ctx ...` searches and inspects local OpenCode history on demand.

## Install

```bash
uv tool install ./bin/ocint --force --no-cache
```

## Safety

- Opens the OpenCode SQLite DB with `mode=ro`.
- Rejects `:memory:` as an OpenCode DB target.
- Runs arbitrary SQL through a single-statement `SELECT`/`WITH` validator and a
  SQLite read-only authorizer.
- Executes `ocint ctx sql` user queries only in an in-memory SQLite sandbox
  populated from stable ctx views, even when the ctx index backend is DuckDB.
- Does not import, refresh, migrate, or mutate OpenCode data.

## ctx backends

`ocint ctx` uses SQLite by default and stores it at `OCINT_CTX_DB` (falling back
to the documented XDG state path). DuckDB can be selected with either:

```bash
OCINT_CTX_BACKEND=duckdb ocint ctx import
ocint ctx --backend duckdb search "native event marker"
```

DuckDB paths are read from `OCINT_CTX_DUCKDB`; SQLite paths are read from
`OCINT_CTX_DB`. Both backends reject `:memory:` for persistent ctx indexes.
DuckDB search requires DuckDB's `fts` extension because imports rebuild a static
FTS index with `PRAGMA create_fts_index(...)`.

## Examples

```bash
ocint state summary --days 30
ocint state models --days 30 --format json
ocint state query "SELECT COUNT(*) AS sessions FROM session"

ocint ctx status
ocint ctx search "ctx skill" --verbose
ocint ctx show session <opencode-session-id> --format markdown --out /tmp/ocint-session.md
ocint ctx docs show sql
ocint ctx sql "SELECT provider, COUNT(*) AS sessions FROM ctx_sessions GROUP BY provider"
ocint ctx compare "native event marker" --source-db /tmp/opencode.sqlite --sqlite-db /tmp/ctx.sqlite --duckdb-db /tmp/ctx.duckdb --json
```

## Reference

https://github.com/ctxrs/ctx
