# ocint Agent Instructions

These instructions apply to `bin/ocint/`.

## Principles

- Separation of concerns: separate policy from mechanisms through APIs; do not create a module, class, or repository merely because code performs I/O. Example: CLI parses `--refresh`; service receives a typed refresh mode.
- Single responsibility: one module should have one reason to change, not one function or class. Keep operations together when they own the same format, transport, or lifecycle. Example: a refresh logging adapter may emit, read, and parse its JSONL format, while the status service decides which records to show.
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
- CLI modules are outer adapters: parse framework input, resolve config, construct typed requests, call exported orchestration, map expected errors, and render.
- Use feature `run.py` modules for complex workflows spanning services, repositories, locks, migrations, workers, or feature-local infrastructure. Keep business rules in `service.py`.
- Production code outside a feature imports supported operations through that feature's `__init__.py`, not private adapters such as `refresh.logging`.
- Services implement business rules independently of CLI frameworks and workflow lifecycle. Example: a service evaluates typed refresh policy without acquiring locks or rendering output.
- A repository provides domain-oriented access to durable application state. Current ctx repositories access SQL-backed state through SQLAlchemy; they contain persistence queries and do not decide command policy.
- Do not introduce a repository for operational artifacts such as logs, temporary files, generated output, or diagnostic streams. Keep their format and I/O in the owning infrastructure adapter unless the artifact becomes a first-class domain data store.
- Parse at the boundary. Example: convert Click strings/env values into typed objects before calling application code.
- Missing required ctx index is an error. Example: `status` fails if ctx DB is required and absent.
- CLI commands must be discoverable without pre-known IDs. Example: `ocint ctx show session` lists recent sessions when no session ID is supplied.
- Do not store behavior data at module scope. Example: no module-level policy, config, schema contracts, security rules, command modes, or behavioral constants.
- Feature config stays with the feature. Example: SQL config belongs under `ctx/sql/`; app config stays in `ctx/config.py`.
- Backend-independent models do not import backend libraries. Example: SQL config models should not import `sqlite3`.

## Repo Conventions

- Module ownership, shared-type placement, and file-creation rules are documented in [module-boundaries.md](docs/architecture/module-boundaries.md).
- Presentation ownership and output boundaries are documented in [presentation.md](docs/architecture/presentation.md).
- Import shared presentation APIs only from the `ocint.presentation` facade. Do not import its private modules directly.
- Keep reusable presentation components, exact machine serializers, and terminal output construction inside `ocint.presentation`.

- Ctx features backed by durable domain state use `service.py`, `repository.py`, and `__init__.py`. This convention does not apply automatically to incidental filesystem I/O or operational artifacts. Example: `ctx/search/service.py` and `ctx/search/repository.py`.
- Ctx DB lifecycle, physical schema, and Alembic files stay under `ctx/db/`. Example: import `ctx_session` from `ocint.ctx.db` in the CLI and physical tables from `ocint.ctx.db.schema` in repositories.
- Do not add root god modules. Example: no `ctx/repository.py`, `ctx/service.py`, or `ctx/workflow.py`.
- Do not re-add root ctx DB ownership modules. Example: no `ctx/db.py`, `ctx/schema.py`, or root `ctx/migrations/` source package.
- Use the package justfile for verification. Example: `just --justfile /home/vikram_orbio_earth/personal/dotfiles-wt/bin/ocint/justfile check`.
- Use root workspace `uv` execution. Example: `uv run --directory /home/vikram_orbio_earth/personal/dotfiles-wt --package ocint --frozen pytest ...`.
- Follow justfile shell variable rules. Example: use `$VAR`, use `$(...)`, do not use `$$VAR`.

### Python conventions

- Do not use nullable dependencies as control flow. Example: no `get_status(None, ...)`.
- Do not branch on raw strings or `None`. Example: use typed modes and `match`, not `if refresh != "off"`.
- **Do not** bypass static checks using `ty: ignore` or `type: ingore` flags. Properly fix issues, not introduce hacks.
- Strictly **NO** module constants in either tests or production code. Introducing them indicates that modeling of the problem has not been done correctly. For example in tests, data should be represented via fixtures. In Python code, it probably means config/settings have not been modeled correctly and instead replaced by module constants.

### Python testing conventions

- Always prefer having tests work on fake data rather than mocking or patching.
- Tests should not need helper functions. Construction of helper functions indicates wrong patterns
- Fixtures are for data, not for creating functions.
- Always follow the GIVEN/WHEN/THEN structure in tests 
- Model one test for one behaviour. If multiple similar cases have to be tested, parameterize rather than putting all in one test.

### Typing

- Prefer concrete types. Construct them wherever appropriate. 
- Do not use `tuple` or `dict` or `object` or `Any`. Create or convert to concrete types.

## Commands

Use the package justfile explicitly:

```sh
just --justfile bin/ocint/justfile test
just --justfile bin/ocint/justfile check
# May require longer timeout, so prefer only during final verification checks
just --justfile bin/ocint/justfile smoke
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
│   ├── architecture/
│   ├── e2e/
│   ├── integration/
│   ├── unit/
│   └── support/  # FIXME: This structure is wrong; tests must not use helper functions.
└── ocint/
    ├── cli/
    │   └── __init__.py
    ├── _config.py
    ├── _errors.py
    ├── _sqlsafe.py
    ├── _timeutil.py
    ├── presentation/
    │   ├── __init__.py
    │   ├── _components.py
    │   ├── _output.py
    │   └── _serialization.py
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
    │   ├── refresh/
    │   │   ├── __init__.py
    │   │   ├── logging.py
    │   │   ├── run.py
    │   │   └── service.py
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

## References

- Presentation ownership and output boundaries: `docs/architecture/presentation.md`
- Release process: `docs/releases.md`

## Justfile Guardrail

- Use `$VAR` for shell variable references.
- Use `$(...)` for command substitution.
- Do not use `$$VAR`.
- Use `{{...}}` only for `just` interpolation.
