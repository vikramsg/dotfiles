# ocint Agent Instructions

These instructions apply to `bin/ocint/`.

## Principles

- Separation of concerns: keep parsing, behavior, persistence, and rendering apart. Example: CLI parses `--refresh`; service receives a typed refresh mode.
- Single responsibility: one module should have one reason to change. Example: a repository loads rows; it does not parse SQL or define sandbox policy.
- Dependency inversion: higher-level behavior receives dependencies explicitly. Example: `search_history(request, repository)`, not `search_history()` reading env.
- Explicit preconditions / fail fast: required infrastructure must exist before command behavior runs. Example: missing ctx DB fails with `run ocint ctx import first`, not an empty status result.
- Type safety: command modes and config are typed at the boundary. Example: use `RefreshMode.OFF`, not `refresh != "off"`.
- Encapsulation: behavior policy is passed explicitly, not hidden in module globals. Example: `run_ctx_sql(repository, sql, config)`, not `_ALLOWED_ACTIONS`.
- Cohesion: feature-specific behavior stays in the owning feature. Example: SQL query policy belongs under `ctx/sql/`, not global app config.
- Single source of truth: contracts are declared once and reused. Example: stable SQL view names, columns, and types come from one typed contract.
- Least privilege: expose only what the command promises. Example: `ctx_events` is queryable; internal tables are denied.
- Make invalid states unrepresentable: avoid `None` or magic strings as behavior signals. Example: no `repository | None` to mean `DB missing`.

## Project Rules

- CLI is the composition root. Example: `ctx/cli.py` creates repositories, sessions, typed config, and request models.
- Services coordinate use cases only. Example: service calls repository and applies typed command behavior.
- Repositories only access persistence. Example: repository executes SQLAlchemy queries; it does not decide command policy.
- Parse at the boundary. Example: convert Click strings/env values into typed objects before calling services.
- Missing required ctx index is an error. Example: `status` fails if ctx DB is required and absent.
- CLI commands must be discoverable without pre-known IDs. Example: `ocint ctx show session` lists recent sessions when no session ID is supplied.
- Do not use nullable dependencies as control flow. Example: no `get_status(None, ...)`.
- Do not branch on raw strings or `None`. Example: use typed modes and `match`, not `if refresh != "off"`.
- Do not store behavior data at module scope. Example: no module-level policy, config, schema contracts, security rules, command modes, or behavioral constants.
- Feature config stays with the feature. Example: SQL config belongs under `ctx/sql/`; app config stays in `ctx/config.py`.
- Backend-independent models do not import backend libraries. Example: SQL config models should not import `sqlite3`.

## Repo Conventions

- Persistence-backed ctx features use `service.py`, `repository.py`, and `__init__.py`. Example: `ctx/search/service.py` and `ctx/search/repository.py`.
- Ctx DB lifecycle, physical schema, and Alembic files stay under `ctx/db/`. Example: import `ctx_session` from `ocint.ctx.db` in the CLI and physical tables from `ocint.ctx.db.schema` in repositories.
- Do not add root god modules. Example: no `ctx/repository.py`, `ctx/service.py`, or `ctx/workflow.py`.
- Do not re-add root ctx DB ownership modules. Example: no `ctx/db.py`, `ctx/schema.py`, or root `ctx/migrations/` source package.
- Use the package justfile for verification. Example: `just --justfile /home/vikram_orbio_earth/personal/dotfiles-wt/bin/ocint/justfile check`.
- Use root workspace `uv` execution. Example: `uv run --directory /home/vikram_orbio_earth/personal/dotfiles-wt --package ocint --frozen pytest ...`.
- Follow justfile shell variable rules. Example: use `$VAR`, use `$(...)`, do not use `$$VAR`.

## Commands

Use the package justfile explicitly:

```sh
just --justfile /home/vikram_orbio_earth/personal/dotfiles-wt/bin/ocint/justfile test
just --justfile /home/vikram_orbio_earth/personal/dotfiles-wt/bin/ocint/justfile check
just --justfile /home/vikram_orbio_earth/personal/dotfiles-wt/bin/ocint/justfile smoke
just --justfile /home/vikram_orbio_earth/personal/dotfiles-wt/bin/ocint/justfile smoke-ctx
just --justfile /home/vikram_orbio_earth/personal/dotfiles-wt/bin/ocint/justfile smoke-state
```

Use root workspace `uv` execution when running tools directly:

```sh
uv run --directory /home/vikram_orbio_earth/personal/dotfiles-wt --package ocint --frozen pytest /home/vikram_orbio_earth/personal/dotfiles-wt/bin/ocint/tests
uv run --directory /home/vikram_orbio_earth/personal/dotfiles-wt --package ocint --frozen ruff check /home/vikram_orbio_earth/personal/dotfiles-wt/bin/ocint/ocint /home/vikram_orbio_earth/personal/dotfiles-wt/bin/ocint/tests
uv run --directory /home/vikram_orbio_earth/personal/dotfiles-wt --package ocint --frozen ruff format --check /home/vikram_orbio_earth/personal/dotfiles-wt/bin/ocint/ocint /home/vikram_orbio_earth/personal/dotfiles-wt/bin/ocint/tests
uv run --directory /home/vikram_orbio_earth/personal/dotfiles-wt --package ocint --frozen ty check /home/vikram_orbio_earth/personal/dotfiles-wt/bin/ocint/ocint /home/vikram_orbio_earth/personal/dotfiles-wt/bin/ocint/tests
```

## Tree

```text
bin/ocint/
├── AGENTS.md
├── justfile
├── pyproject.toml
├── implementation_notes.md
├── docs/
├── tests/
└── ocint/
    ├── cli/
    │   ├── __init__.py
    │   └── _render.py
    ├── _config.py
    ├── _errors.py
    ├── _render.py
    ├── _sqlsafe.py
    ├── _timeutil.py
    ├── ctx/
    │   ├── cli.py
    │   ├── config.py
    │   ├── docs.py
    │   ├── history.py
    │   ├── models.py
    │   ├── render.py
    │   ├── transcript.py
    │   ├── db/
    │   │   ├── __init__.py
    │   │   ├── connection.py
    │   │   ├── schema.py
    │   │   └── migrations/
    │   ├── importing/
    │   │   ├── service.py
    │   │   └── repository.py
    │   ├── search/
    │   │   ├── service.py
    │   │   └── repository.py
    │   ├── show/
    │   │   ├── service.py
    │   │   └── repository.py
    │   ├── locate/
    │   │   ├── service.py
    │   │   └── repository.py
    │   ├── sql/
    │   │   ├── models.py
    │   │   ├── service.py
    │   │   └── repository.py
    │   └── status/
    │       ├── service.py
    │       └── repository.py
    └── opencode/
        ├── models.py
        └── repository.py
```

## Justfile Guardrail

- Use `$VAR` for shell variable references.
- Use `$(...)` for command substitution.
- Do not use `$$VAR`.
- Use `{{...}}` only for `just` interpolation.
