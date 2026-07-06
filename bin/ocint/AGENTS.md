# ocint Agent Instructions

These instructions apply to `bin/ocint/`.

## Principles

- Separation of concerns: CLI handles command I/O, services handle use-case behavior, repositories handle persistence.
- Composition root: `ocint/ctx/cli.py` constructs repositories, sessions, source adapters, reads env, and runs migrations.
- Single responsibility: do not mix persistence, policy, parsing, rendering, and orchestration in one module.
- Dependency inversion: services receive typed dependencies and request models; services do not construct repositories or DB sessions.
- Type safety: avoid stringly typed modes and broad `Any`; prefer `Literal`, enums, protocols, or typed models.
- Encapsulation: avoid mutable module-level policy globals, especially for security-sensitive behavior.
- Single source of truth: do not duplicate schema contracts, stable SQL view contracts, or command contracts without tests.
- Cohesion: persistence-backed ctx features live in focused packages with `service.py`, `repository.py`, and `__init__.py`.
- Explicitness over cleverness: prefer direct command flow over generic callback helpers when readability suffers.
- Least privilege: SQL access must expose only stable public ctx surfaces and fail closed.

## ctx Boundaries

- `ctx/cli.py`: command handlers, dependency construction, env reads, session lifecycle, migrations.
- `ctx/*/service.py`: use-case behavior only.
- `ctx/*/repository.py`: SQL/database access only.
- `ctx/models.py`: typed request/result/read models.
- `ctx/db.py`: SQLAlchemy/Alembic lifecycle helpers.
- `ctx/config.py`: ctx configuration/path resolution.
- `ctx/migrations/`: Alembic migrations.
- `ctx/render.py`: output formatting only.
- Do not add root god modules like `ctx/repository.py`, `ctx/service.py`, or `ctx/workflow.py`.
- Do not add generic `store/` or `persistence/` packages.

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
    ├── cli.py
    ├── _config.py
    ├── _errors.py
    ├── _render.py
    ├── _sqlsafe.py
    ├── _timeutil.py
    ├── ctx/
    │   ├── cli.py
    │   ├── config.py
    │   ├── db.py
    │   ├── docs.py
    │   ├── history.py
    │   ├── models.py
    │   ├── render.py
    │   ├── schema.py
    │   ├── transcript.py
    │   ├── migrations/
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
