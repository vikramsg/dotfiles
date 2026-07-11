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
- `service.py`: Implement application behavior.
- `repository.py`: Read and write durable application data.
- `models.py`: Define types shared by multiple files.
- `config.py`: Define typed settings and runtime configuration.
- `logging.py`: Configure and manage application logs.
- `render.py`: Turn results into human-readable output.
- `__init__.py`: Define the package's public imports.

Repositories are for durable application data. Operational logs, temporary
files, generated output, and diagnostic streams remain with their owning
adapter unless they become first-class application data.

## Shared types

- Keep a type in its owning file while only that file uses it.
- Move a type used by multiple files into `models.py` in their closest common
  package.
- A `models.py` contains type declarations only: models, enums, protocols, and
  type aliases.
- Do not put functions, services, I/O, or behavior helpers in `models.py`.

## Configuration

Configuration is typed data, not a collection of functions.

- Environment-backed values belong to a `Settings` class derived from
  `pydantic_settings.BaseSettings`.
- Settings own environment names, defaults, and environment parsing.
- Resolved runtime configuration belongs to a Pydantic `BaseModel`.
- Application code receives resolved configuration explicitly.
- Do not read `os.environ` outside a `Settings` class.
- Do not place standalone parsing or resolution functions in `config.py`.

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

## Patterns and anti-patterns

### Pattern: generic contract with a concrete implementation

`ocint/_models.py` declares the `CliOutput` and `CliProgress` protocols.
`ocint/presentation/_output.py` provides concrete terminal implementations.
The shared contract does not import the implementation.

### Pattern: shared feature types

Types used by a feature's service, repository, and renderer live in that
feature's `models.py`. Types used by only one of those files remain local.

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

### Anti-pattern: unnecessary file or repository

A new file exists only for one helper, or a repository is introduced for an
operational artifact that is not durable application data.
