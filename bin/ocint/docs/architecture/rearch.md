# Compiling global configuration without global coupling

## Problem

ocint needs one daemon configuration file and one model that validates the
whole file. That model must know every config section. The mistake is not the
aggregate itself; the mistake is allowing runtime features to import it.

The target dependency rule is:

```text
The aggregate imports every concrete config section.
No config section or runtime feature imports the aggregate.
Only composition and config-management code receives the aggregate type.
Runtime features receive narrow protocols or domain services.
```

This note makes that rule concrete for Python imports, Pydantic parsing, and
ocint dependency injection. It distills the useful parts of
[dotfiles PR 212](https://github.com/vikramsg/dotfiles/pull/212), which analyzed
[OpenCode revision 849c2598](https://github.com/anomalyco/opencode/tree/849c2598abc7d2b40261e74b5826bc74ffc78308).

## The unavoidable dependency

An aggregate schema must depend on all of its sections:

```text
                    aggregate.py
                   /     |      \
                  v      v       v
              git.py  github.py  opencode.py
```

Trying to remove these imports with registration decorators, import side
effects, or a plugin registry only hides the dependency. It also makes config
completeness depend on import order.

Keep the dependency static and visible. The important property is that it is
one-way:

```text
GOOD

aggregate.py ------> git config section
       |
       +-----------> GitHub config section
       |
       `-----------> OpenCode config section


BAD

aggregate.py ------> git config section
     ^                    |
     |                    |
     `------ Git runtime -+
```

The aggregate is the one module allowed to know all config models. That does
not make it a runtime API.

## Concrete module layout

Replace the single `daemon/config.py` with a small aggregate package and
feature-owned config modules. Existing flat features become packages only when
their config and runtime implementation need independent import boundaries:

```text
ocint/daemon/
├── config/
│   ├── __init__.py       # narrow facade: DaemonConfig, DaemonContext
│   ├── aggregate.py      # root composition and cross-section validation
│   ├── context.py        # DaemonSettings, DaemonContext, file loading
│   └── repository.py     # daemon-wide repository config and registry
├── api/
│   ├── config.py         # ApiConfig
│   └── router.py         # FastAPI adapter
├── execution/
│   ├── config.py         # SchedulerConfig and command limits
│   └── service.py        # JobExecutor and job policy
├── git/
│   ├── config.py         # GitConfig
│   └── manager.py        # GitManager
├── github/
│   ├── config.py         # GitHubConfig
│   └── service.py
├── lch/
│   ├── config.py         # LifecycleConfig
│   └── ...
├── logging/
│   ├── config.py         # LoggingConfig
│   └── service.py
└── opencode/
    ├── config.py         # OpenCodeConfig
    └── client.py         # OpenCode HTTP/process adapter
```

Each feature `config.py` contains its concrete Pydantic schema, defaults, and
validators. It does not contain Git commands, HTTP calls, workflow behavior, or
feature service ports. The root config package does not become a collection of
all feature settings; it only composes them and owns daemon-wide config.

Do not split files more finely than the schema requires. For example, keep
closely related scheduler and command execution limits together while they
share one lifecycle.

## What compiles the global config

`config/aggregate.py` statically imports every section and composes the root
Pydantic model:

```python
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ocint.daemon.api.config import ApiConfig
from ocint.daemon.config.repository import RepositoryConfig
from ocint.daemon.execution.config import SchedulerConfig
from ocint.daemon.git.config import GitConfig
from ocint.daemon.github.config import GitHubConfig
from ocint.daemon.lch.config import LifecycleConfig
from ocint.daemon.logging.config import LoggingConfig
from ocint.daemon.opencode.config import OpenCodeConfig


class DaemonConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    database_path: Path
    mirror_root: Path
    worktree_root: Path
    repositories: tuple[RepositoryConfig, ...] = Field(min_length=1)
    scheduler: SchedulerConfig
    lifecycle: LifecycleConfig
    logging: LoggingConfig
    opencode: OpenCodeConfig
    api: ApiConfig
    github: GitHubConfig
    git: GitConfig
    idle_timeout_seconds: int

    @model_validator(mode="after")
    def validate_cross_section_rules(self) -> "DaemonConfig":
        ...
```

Pydantic compiles this type graph from the field annotations. No runtime
registration is needed. `DaemonConfig.model_validate(raw_toml)` recursively
parses each nested section using its concrete owner.

`aggregate.py` owns only:

- the top-level document shape;
- section composition;
- defaults that apply to the whole document;
- invariants spanning sections;
- exact serialization of the complete document.

It does not own feature behavior, config source I/O, secrets, or protocols.

## What parses it

`config/context.py` owns source selection and parsing:

```text
environment
    |
    v
DaemonSettings.config_path(home)
    |
    v
read TOML once
    |
    v
DaemonConfig.model_validate(raw mapping)
    |
    v
one immutable aggregate for this CLI invocation / daemon process
```

`DaemonSettings` continues to own environment-backed values and secrets.
`DaemonContext` continues to own the lazy file read. The parser imports
`DaemonConfig`; section modules do not import the parser.

ocint currently has one config source and one resolved scope. It does not need
a `ConfigService`. Add a service only if config gains live updates, source
precedence, invalidation, or multiple simultaneous scopes.

## What injects it

`daemon/cli.py` is the composition root. It may import the aggregate and every
concrete implementation because its job is wiring:

```text
                        daemon/cli.py
                             |
              load and validate DaemonConfig
                             |
          +------------------+------------------+
          |                  |                  |
          v                  v                  v
  config.scheduler    config.repositories  config.github
          |                  |                  |
          v                  v                  v
  ExecutionPolicy    RepositoryCatalog   GitHubPollingPolicy
          |                  |                  |
          +---------> JobExecutor               |
                             ^                  |
                             |                  v
                             +----------- GitHubService
```

The aggregate is deconstructed at this boundary. It is never passed as a
parameter named `config` to a runtime service.

A concrete composition sketch is:

```python
config = context.config()
repositories = ConfiguredRepositories(config.repositories)

git = GitManager(
    mirror_root=config.mirror_root,
    worktree_root=config.worktree_root,
    command_policy=config.scheduler,
    ssh_policy=config.git,
    ...
)
github = GitHubService(
    polling_policy=config.github,
    repositories=repositories,
    client=github_client,
    repository=github_repository,
    tasks=tasks,
)
executor = JobExecutor(
    execution_policy=config.scheduler,
    repositories=repositories,
    store=control_repository,
    opencode=opencode,
    git=git,
    github=github,
)
```

The exact constructor grouping can change during implementation. The invariant
is that `GitHubService` and `JobExecutor` do not import or annotate
`DaemonConfig`.

## How feature imports work

Runtime consumers declare the smallest interface they read. They do not import
the concrete config section merely because that section currently implements
the interface.

```python
# daemon/service.py
class ExecutionPolicy(Protocol):
    @property
    def capacity(self) -> int: ...

    @property
    def job_timeout_seconds(self) -> int: ...

    @property
    def shutdown_timeout_seconds(self) -> int: ...


class JobExecutor:
    def __init__(self, execution_policy: ExecutionPolicy, ...) -> None:
        ...
```

`SchedulerConfig` does not inherit from or import `ExecutionPolicy`. Structural
typing checks conformance when `daemon/cli.py` passes the concrete object to
`JobExecutor`.

The resulting import graph is:

```text
                          daemon/models.py
                        shared stable protocols
                           ^       ^       ^
                           |       |       |
service.py ----------------+       |       +------ github/service.py
                                   |
git.py ----------------------------+

config section modules             runtime feature modules
          ^                                  ^
          |                                  |
          +--------- config/aggregate.py     |
                              ^              |
                              |              |
                              +--- daemon/cli.py
```

There is no arrow from a runtime feature to `config/aggregate.py`.

### Python package initialization

Python executes `feature/__init__.py` before loading `feature/config.py`.
Therefore a feature facade imported by `aggregate.py` must not eagerly import
its router, client, manager, repository, or service implementation.

```text
aggregate.py
    |
    v
api/__init__.py       must stay dependency-light
    |
    v
api/config.py         safe schema import

api/__init__.py -X-> api/router.py -> FastAPI and runtime dependencies
```

Keep affected `__init__.py` files limited to eager config and contract exports.
Runtime operations that must remain available through the feature facade use a
deliberate lazy export: importing `feature.config` does not resolve it, while
`from feature import create_router` does. Cover both import paths with tests;
do not restore eager exports that make config parsing load the application.

## Protocol placement

Do not respond to global config coupling by moving every config view into
`daemon/models.py`.

Use this placement rule:

```text
one runtime consumer
    -> protocol beside that consumer

independent sibling consumers with the same meaning and lifecycle
    -> protocol in daemon/models.py

external validation and defaults
    -> concrete model in the owning feature's config.py
```

Concrete examples:

| Contract | Owner | Reason |
| --- | --- | --- |
| `ExecutionPolicy` | `service.py` | Only `JobExecutor` consumes scheduler lifecycle policy. |
| Git command/SSH policy | `git.py` | Only `GitManager` consumes it. |
| GitHub polling policy | `github/service.py` | Only GitHub polling consumes it. |
| `RepositoryPolicy` | `daemon/models.py` | Execution, Git, and GitHub share repository identity and authorization vocabulary. |
| `RepositoryCatalog` | `daemon/models.py` if both execution and GitHub use identical lookup semantics | It is a shared domain capability, not raw config. |
| `LogRotation` | `daemon/models.py` | Logging and concrete config share a stable cross-boundary policy. |

If two local protocols happen to have the same fields but different meanings,
keep both. Shape equality is not shared ownership.

## Repository configuration needs a resolver

The current `DaemonConfig.repository(name)` method combines aggregate config
with runtime lookup. Move that lookup into a small concrete registry built by
the composition root:

```text
tuple[RepositoryConfig, ...]
             |
             v
 ConfiguredRepositories
             |
             +--> get(name) -> RepositoryPolicy
             `--> list() ----> tuple[RepositoryPolicy, ...]
```

`JobExecutor` asks the registry for one repository. `GitHubService` asks it for
configured repositories. Neither knows where the policies came from or how the
global document stores them.

This is a real config-to-domain boundary. It removes repository lookup behavior
from the aggregate and prevents callers from traversing `config.repositories`
directly.

## Config-management exceptions

Some outer operations must handle the complete document:

- `config show` serializes the complete aggregate;
- provisioning creates a complete aggregate and writes TOML;
- migration may inspect a complete document version;
- cross-section diagnostics may validate relationships between sections.

These are config-management operations, not runtime features. They may import
`DaemonConfig` through the `ocint.daemon.config` facade.

LCH diagnostics that inspect one section should still accept that section or a
narrow protocol. Only diagnostics that genuinely compare sections receive the
aggregate.

## What OpenCode teaches

OpenCode gets three important decisions right:

1. Its external `ConfigV1.Info` composes feature-owned schemas.
2. Config loading and source precedence are explicit behind `Config.Service`.
3. Resolved config is scoped by active directory instead of stored as one
   mutable process-global value.

OpenCode also shows the remaining failure mode: Agent, LLM, MCP, and session
code still import the broad config service or root config type in places. An
injected global model is still a global model from the type dependency's point
of view.

ocint should use OpenCode's explicit composition and scope, but stop one step
earlier at runtime boundaries:

```text
OpenCode in coupled paths

Config.Service.get() -> ConfigV1.Info -> runtime helper reads one field


ocint target

DaemonConfig -> CLI composition -> narrow policy -> runtime helper
```

ocint does not need OpenCode's Effect layer graph. Constructor and function
injection from `daemon/cli.py` provides the required boundary.

## Enforcement

Add architecture tests with explicit import rules:

1. Only `daemon/config/aggregate.py`, `daemon/config/context.py`,
   `daemon/config/__init__.py`, `daemon/cli.py`, and designated config-management
   modules may import `DaemonConfig`.
2. Runtime modules such as `service.py`, `git.py`, `github/service.py`,
   `opencode.py`, `tasks/`, and repositories may not import
   `ocint.daemon.config.aggregate` or `DaemonConfig`.
3. Feature config modules may not import `aggregate.py`, `context.py`, CLI,
   services, or adapters. They may import narrow shared value types when those
   types are part of their schema.
4. `aggregate.py` may import concrete config section modules but no runtime
   implementations, frameworks, database modules, or presentation modules.
5. Feature `__init__.py` modules reached while importing config sections may
   not eagerly import runtime implementations or frameworks.
6. `daemon/models.py` may not import the config package.
7. An import smoke test must load `ocint.daemon.config`, `daemon.cli`, and each
   runtime feature to catch package facade cycles.
8. Strict type checking at `daemon/cli.py` verifies that concrete Pydantic
   sections satisfy consumer protocols without ignores or casts.

The architecture should fail if a developer takes the convenient shortcut:

```python
from ocint.daemon.config import DaemonConfig


class NewFeature:
    def __init__(self, config: DaemonConfig) -> None:
        ...
```

## Migration order

```text
1. Create aggregate package and feature-owned config modules
                    |
                    v
2. Keep behavior unchanged; aggregate still validates the same TOML
                    |
                    v
3. Add local/shared policy protocols
                    |
                    v
4. Build ConfiguredRepositories at CLI composition
                    |
                    v
5. Replace DaemonConfig constructor parameters with narrow dependencies
                    |
                    v
6. Add import guards, then remove aggregate imports from runtime modules
```

Do not move schemas and redesign runtime constructors in one step. First make
the aggregate compilation explicit, then remove inward dependencies one
consumer at a time. The external TOML shape and defaults remain unchanged
throughout.

## Result

The final system still has a global aggregate, because parsing a global file
requires one. Coupling is removed by controlling import direction and ending
the aggregate's lifetime at the composition boundary:

```text
all config models ---> aggregate ---> parser ---> composition root
       |                                             |
       |                                             v
       |                                  protocols/domain services
       |                                             |
       `---- no imports from runtime <---------------+
```

The aggregate knows all config sections. Features do not know the aggregate.
That asymmetry is the architecture.

## Upstream evidence

- Root schema composition: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/core/src/v1/config/config.ts#L3-L18
- Config service interface: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/config/config.ts#L117-L137
- Global and project source merging: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/config/config.ts#L398-L410
- Instance-scoped config state: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/config/config.ts#L600-L608
- Provider domain service: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/provider/provider.ts#L1148-L1172
- Broad config read in LLM: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/session/llm.ts#L95-L103
