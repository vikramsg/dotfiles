# Module boundaries

## Purpose

This document defines when to create files, what common files own, where shared
types belong, and how dependencies should flow.

## Creating files

- Create a file when its responsibility is substantial or shared.
- Do not create a file merely to isolate one helper or one I/O call.
- Keep code together when it changes for the same reason.
- Split code when it has independent consumers or independent reasons to change.

## File responsibilities

- `cli.py`: Parse inputs and wire components together.
- `run.py`: Coordinate a feature's complex application workflow across services, repositories, locks, and infrastructure.
- `service.py`: Implement business rules independently of framework and workflow lifecycle.
- `repository.py`: Read and write durable application data.
- `models.py`: Define types shared by multiple files.
- `config.py`: Define typed settings and runtime configuration.
- `logging.py`: Configure and manage application logs.
- `render.py`: Turn results into human-readable output.
- `__init__.py`: Define the package's public imports.

`cli.py` is an outer adapter and composition root: it parses framework inputs,
resolves configuration, constructs typed requests, calls exported application
operations, maps expected failures to framework errors, and selects rendering.
`run.py` owns multi-step application orchestration that would otherwise turn the
CLI into the workflow implementation. `service.py` retains business rules that
can be evaluated independently of CLI, persistence, and process mechanics.

Repositories are for durable application data. Operational logs, temporary
files, generated output, and diagnostic streams remain with their owning
adapter unless they become first-class application data.

## Shared types

- Keep a type in its owning file while only that file uses it.
- Move a type only when it is a stable contract owned by its closest common
  package. Import count alone does not justify promotion.
- A `models.py` contains type declarations only: models, enums, protocols, and
  type aliases.
- Do not put functions, services, I/O, or behavior helpers in `models.py`.

Choose the narrowest owner:

| Use | Location |
| --- | --- |
| One module | Keep the type in that module |
| Sibling modules in one subfeature | The subfeature's `models.py` |
| Sibling subfeatures with the same vocabulary and lifecycle | The parent feature's `models.py` |
| Unrelated application features | A deliberately narrow application contract, not a root dumping ground |

A parent `models.py` is reserved for its package's core vocabulary. Types belong
together only when they share meaning, lifecycle, and reasons to change with
that package. If a models module mixes unrelated transport, persistence,
rendering, configuration, and infrastructure concerns, move each group down to
its closest owner.

Keep adapter and workflow details local even when several implementation files
use them. Examples include external API payloads, database row representations,
renderer view data, infrastructure diagnostics, derived filesystem settings,
and request or result types used by one workflow.

## Configuration

Configuration is typed data, not a collection of functions.

- Environment-backed values belong to a `Settings` class derived from
  `pydantic_settings.BaseSettings`.
- Settings own environment names, defaults, and environment parsing.
- Resolved runtime configuration belongs to a Pydantic `BaseModel`.
- Application code receives resolved configuration explicitly.
- Do not read `os.environ` outside a `Settings` class.
- Do not place standalone parsing or resolution functions in `config.py`.

External boundaries construct typed values. CLI, HTTP, configuration, database,
and external API adapters validate raw input and map it into immutable models.
Inner workflows and services receive those values explicitly; they do not read
environment variables, load configuration, or assemble policy from raw values.

## Dependency direction

- The wider a module's use, the more generic its contracts should be.
- Shared modules expose protocols and data types, not concrete implementations.
- Concrete implementations depend on shared contracts.
- Shared contracts do not import database, terminal, filesystem, or framework
  implementations.
- Feature-specific types stay in the closest feature package that owns them.

## Public APIs

- Packages expose supported types and functions through `__init__.py`.
- Callers use package APIs rather than private implementation modules.
- Private modules may change without preserving an external contract.
- Production callers outside a feature package import supported operations from
  that feature's `__init__.py` facade, not from private adapter or implementation
  modules.

## Patterns and anti-patterns

### Pattern: generic contract with a concrete implementation

`ocint/_models.py` declares the `CliOutput` and `CliProgress` protocols.
`ocint/presentation/_output.py` provides concrete terminal implementations.
The shared contract does not import the implementation.

### Pattern: CLI delegates workflow to a run module

```python
request = RefreshWorkerRequest(...)
try:
    run_refresh_worker(request, sql_config, expected_revision)
except ExpectedInfrastructureError as error:
    raise click.ClickException(str(error)) from error
```

The CLI owns Click and construction. `refresh/run.py` owns the lock, migration,
attempt lifecycle, import execution, and feature-local logging coordination.
Business decisions remain in `refresh/service.py`.

### Pattern: shared feature types

Types used by a feature's service, repository, and renderer live in that
feature's `models.py` when they express the same feature vocabulary. Types used
by only one file remain local. Types shared only within a narrower subfeature
belong in that subfeature's `models.py`.

For example, `daemon/models.py` may own daemon-wide job and policy contracts
used across execution, persistence, API, and integrations. LCH status, GitHub
transport payloads, OpenCode transport payloads, logging internals, and renderer
values remain with their owning subfeatures or adapters. Their presence under
the daemon package does not make them daemon-wide domain models.

### Pattern: typed settings and configuration

```python
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class FeatureSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FEATURE_")

    data_path: Path | None = None
    timeout: str = "30s"


class FeatureConfig(BaseModel):
    data_path: Path
    timeout_ms: int
```

### Anti-pattern: functional configuration

`ocint/ctx/config.py` is an existing anti-pattern: it is primarily environment
reads, parsing functions, and path-resolution functions rather than settings
and configuration models.

```python
def resolve_data_path() -> Path:
    value = os.environ.get("FEATURE_DATA_PATH")
    ...
```

### Anti-pattern: inverted dependency

A shared model or protocol imports a concrete database, terminal, filesystem,
or framework implementation.

### Anti-pattern: misplaced shared type

A type used by multiple files remains declared inside one consumer instead of
their closest common `models.py`.

### Anti-pattern: dumping-ground models module

A parent `models.py` collects unrelated types merely because several files
import them. Import count is being used as ownership. Keep each type local or
move it to the narrowest package whose vocabulary, lifecycle, and change reasons
it represents.

### Anti-pattern: unnecessary file or repository

A new file exists only for one helper, or a repository is introduced for an
operational artifact that is not durable application data.

### Anti-pattern: CLI-owned workflow or private cross-package import

A CLI that acquires feature locks, starts attempt state, runs migrations, or
executes workers owns application workflow that belongs in `run.py`. A caller
outside `refresh/` importing `refresh.logging` bypasses the feature facade and
couples production code to a private adapter.
