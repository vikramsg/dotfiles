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
- Installs `ctx_*` SQL views only as temporary connection-local views.
- Does not import, refresh, migrate, or mutate OpenCode data.

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
```

## Reference

https://github.com/ctxrs/ctx
