# ocint

`ocint` is a standalone UV package for OpenCode SQLite inspection and local ctx history search.

It exposes exactly one console script:

```bash
ocint
```

Command groups:

- `ocint state ...` provides OpenCode usage analytics.
- `ocint ctx ...` searches and inspects local OpenCode history via a persistent index.

## Install

```bash
uv tool install ./bin/ocint --force --no-cache
```

## Safety

- Opens the OpenCode SQLite DB with `mode=ro`.
- Rejects `:memory:` as an OpenCode DB target.
- Runs arbitrary SQL through a single-statement `SELECT`/`WITH` validator and a
  SQLite read-only authorizer.
- Never mutates OpenCode data. `ctx` refresh writes only to the ocint-owned ctx index.

## ctx Refresh

`ocint ctx search` reads the persistent ctx index. Default search imports a missing index, searches stale ready indexes immediately, and refreshes them in the background (TTL default 60m). `ocint ctx status` shows index readiness, freshness, source DB, refresh log path, and the latest refresh attempt.

## Examples

```bash
ocint state summary --days 30
ocint state sessions --days 30 --format json
ocint state query "SELECT COUNT(*) AS sessions FROM session"

ocint ctx status
ocint ctx search "ctx skill" --verbose
ocint ctx show session <opencode-session-id> --format markdown --out /tmp/ocint-session.md
ocint ctx docs show sql
ocint ctx sql "SELECT provider, COUNT(*) AS sessions FROM ctx_sessions GROUP BY provider"
```

## Reference

https://github.com/ctxrs/ctx
