# OpenCode configuration lessons for ocint modularity

## Scope

This note distills the OpenCode configuration analysis in
[dotfiles PR 212](https://github.com/vikramsg/dotfiles/pull/212) and connects it
to ocint's protocol-first rearchitecture. The upstream evidence is pinned to
[OpenCode revision 849c2598](https://github.com/anomalyco/opencode/tree/849c2598abc7d2b40261e74b5826bc74ffc78308).

The useful lesson is not that ocint should reproduce OpenCode's Effect service
graph. It is that one user-facing configuration document, one config file, or
one application process does not require one internal configuration owner or
one model imported by every module.

## OpenCode in four boundaries

OpenCode separates configuration into four boundaries:

```text
feature schemas
      |
      v
aggregate external schema
      |
      v
source discovery, precedence, validation and merging
      |
      v
instance-scoped resolved configuration
      |
      v
domain services and runtime values
```

### 1. Feature schemas compose one external contract

OpenCode's root `ConfigV1.Info` is the user-facing JSON shape, but agent,
provider, MCP, formatter, LSP, permission, plugin, server, and skill schemas are
declared by their owning features. The root schema composes them.

This permits a single documented config file without requiring one source file
to own the details of every feature. The aggregate owns document composition;
features own the meaning and validation of their sections.

### 2. Loading is a service, not an ambient object

OpenCode exposes config reads, updates, invalidation, and directory discovery
through an injected `Config.Service`. Its implementation receives filesystem,
environment, account, authentication, package, and HTTP dependencies through
the layer graph.

This makes loading and mutation explicit and replaceable. A module cannot
silently read a process-global object merely because configuration is widely
available.

### 3. Global is a source precedence, not a lifetime

OpenCode merges global files, explicit paths, discovered project files,
directory content, inline content, account data, and managed configuration in
a defined order. The resolved result is cached by active instance directory
and invalidated with that instance.

The word "global" therefore identifies an early configuration source. It does
not mean that all projects in a server share one mutable resolved object.

### 4. Domain services absorb configuration

Provider and agent services read resolved configuration while constructing
their state, then expose provider models, agents, tools, and operations. Their
callers usually work with domain values rather than config fragments.

The boundary is:

```text
external config -> feature initialization -> domain API -> runtime consumers
```

This is more modular than passing the root config through every call.

## The caution in OpenCode

OpenCode does not completely isolate features from its aggregate. Agent,
Provider, LLM, MCP, and session code still import `Config.Service` or the root
`ConfigV1.Info` type in places. Some helpers accept the whole config even when
they read one nested policy.

Injection improves lifecycle and test replacement, but a broad injected
dependency remains broad. A field rename in the root schema can still force
unrelated runtime modules to change.

ocint should adopt OpenCode's separation of external schema, resolution scope,
and runtime domain APIs, while using narrower contracts than OpenCode where the
consumer needs only a small policy view.

## Current ocint shape

ocint already has several useful boundaries:

- `DaemonSettings` owns environment-backed paths, secrets, and process values.
- `DaemonContext.config()` is the configuration load boundary.
- `DaemonConfig` is the validated aggregate for one daemon configuration file.
- `daemon/cli.py` is the composition root and constructs concrete adapters.
- Concrete OpenCode, Git, GitHub, API, logging, scheduler, lifecycle, and
  repository settings are immutable Pydantic models.

The main coupling occurs after validation:

- `JobExecutor` receives all of `DaemonConfig`.
- `GitHubService` receives all of `DaemonConfig`.
- authorization and Git provisioning accept concrete `RepositoryConfig`.
- LCH diagnostics, rendering, and provisioning import the aggregate config.
- `service.py` imports concrete config classes while also owning shared job
  models and workflow ports.

The current flow is therefore:

```text
daemon.toml
    |
    v
DaemonContext.config()
    |
    v
DaemonConfig ------------------------------+
    |                                      |
    +--> CLI composition                   |
    +--> JobExecutor ----------------------+ broad aggregate dependency
    +--> GitHubService --------------------+
    +--> LCH diagnostics/render/provision -+
```

This is manageable while the daemon is small, but it makes the aggregate model
an attractive shortcut for every new feature.

## Recommended ocint model

Keep one aggregate external configuration while making runtime dependencies
narrower:

```text
                         daemon.toml
                              |
                              v
                DaemonSettings + DaemonContext
                    source and load boundary
                              |
                              v
                         DaemonConfig
                 validated aggregate document
                              |
                   daemon/cli.py composition
                  /           |             \
                 v            v              v
       RepositoryPolicy  ExecutionPolicy  GitHubPolicy
          protocol          protocol        protocol
              |                |               |
              v                v               v
         Git/service      JobExecutor      GitHubService
```

`DaemonConfig` remains concrete because TOML validation, defaults, cross-field
checks, serialization, provisioning, and `config show` need a complete runtime
model. Runtime modules should not depend on it by default.

The composition root can pass concrete nested Pydantic values directly when
they structurally satisfy read-only protocols. A second copied settings model
is unnecessary unless the feature performs a real transformation from external
configuration to runtime state.

## Configuration ownership rules

### The root owns aggregation

Root config owns:

- the complete external document;
- cross-section invariants, such as unique repository names and distinct
  storage roots;
- configuration source selection and loading;
- composition of feature-owned config sections;
- exact serialization needed by provisioning and `config show`.

It should not own feature behavior merely because behavior is configurable.

### Features own section meaning

A concrete config section should move to a feature package when it has an
independent schema, validation rules, defaults, and reasons to change. The root
aggregate may import and compose that model.

Do not split `config.py` mechanically into one file per class. `ApiConfig` or
`GitConfig` should move only when the destination has substantial feature
ownership. File count is not modularity.

### Consumers own narrow runtime ports

A protocol belongs next to its consumer when one workflow uses it. Promote it
to `daemon/models.py` only when independent sibling features share the same
stable vocabulary and lifecycle.

Examples:

- A scheduler/execution policy used only by `JobExecutor` belongs in
  `service.py`.
- A Git command policy used only by `GitManager` belongs in `git.py`.
- `RepositoryPolicy` may belong in `daemon/models.py` if service, Git, and
  GitHub independently consume the same repository identity and policy.
- `LogRotation` is a stable cross-boundary policy contract; concrete defaults
  and validation remain in `LoggingConfig`.

This is how protocol-first design avoids turning `models.py` into a registry of
every protocol in the package.

### Runtime services expose domain APIs

After a feature consumes configuration, callers should use its domain API. A
caller should ask a repository registry for an authorized repository, a
provider service for a model, or an executor to submit work. It should not
inspect the root config to reproduce those decisions.

For ocint, repository lookup and actor authorization are candidates for one
cohesive policy API. That API can return a `RepositoryPolicy` without exposing
the entire `DaemonConfig` or requiring every caller to implement lookup rules.

## What to adopt

1. Keep one validated external daemon document while allowing feature-owned
   section schemas.
2. Treat config loading as an explicit outer-boundary operation.
3. Define the scope of every resolved config value. Today that scope is one CLI
   invocation or daemon process; future per-worktree overlays must be keyed by
   worktree or repository rather than stored in one process singleton.
4. Resolve source precedence before constructing runtime services.
5. Pass concrete config values through narrow read-only protocols.
6. Let domain services translate config into runtime state and expose domain
   operations to callers.
7. Keep secrets and process environment in `DaemonSettings`; do not add them to
   broad domain contracts.
8. Test aggregate validation separately from protocol conformance and feature
   behavior.

## What not to copy

1. Do not add an Effect-style dependency framework. Python constructor and
   function injection at `daemon/cli.py` is sufficient.
2. Do not introduce a `ConfigService` merely to wrap the existing one-time
   `DaemonContext.config()` read. A service is justified only by multiple
   sources, updates, invalidation, or multiple simultaneous scopes.
3. Do not inject all of `DaemonConfig` behind a protocol with the same fields.
   That hides the concrete name but preserves the coupling.
4. Do not let feature types index into or alias nested root config types. Import
   the feature-owned type or consume a protocol.
5. Do not pass the aggregate to helpers that need one or two values.
6. Do not put feature config models or consumer-local config protocols in root
   `daemon/models.py` solely because configuration is shared infrastructure.
7. Do not add project overlays until ocint has a real requirement for multiple
   resolved scopes in one process.

## Connection to the protocol-first plan

The protocol-first `models.py` plan and the OpenCode config lesson solve
different parts of the same dependency problem:

- The aggregate Pydantic config is an external boundary model.
- Protocols are runtime consumer views.
- Enums are shared closed vocabulary.
- Domain services own behavior and consumer ports.
- Adapters own transport and persistence models.

The aggregate should not move into `models.py`, and protocols should not move
into `config.py`. Their dependency direction is:

```text
daemon/models.py protocols <--- config.py concrete models
             ^                            |
             |                            |
       runtime consumers <-------- CLI composition
```

Python structural typing allows `RepositoryConfig` and `LoggingConfig` to
satisfy read-only protocols without importing protocol implementations or
duplicating data. The strict type checker is the conformance test.

## Incremental application

Apply these lessons with the protocol-first migration rather than as a separate
config rewrite:

1. Inventory which `DaemonConfig` fields each service and helper reads.
2. Move shared stable policy protocols to `daemon/models.py`; keep single-
   consumer protocols beside the consumer.
3. Change authorization, Git provisioning, and GitHub behavior to consume the
   narrowest policy that preserves their semantics.
4. Change `JobExecutor` to consume an executor-owned policy view rather than
   `DaemonConfig`.
5. Keep `daemon/cli.py` responsible for loading the aggregate and wiring
   concrete values into those contracts.
6. Add architecture tests prohibiting aggregate config imports from core
   service and adapter modules where a narrow contract exists.
7. Reassess concrete config file placement only after runtime coupling has been
   removed. Moving classes first would change paths without changing the
   architecture.

## Decision test for future configuration

For each new setting, answer these questions before choosing its location:

1. Which external source defines it?
2. Which feature owns its validation and default?
3. What is the lifetime and scope of its resolved value?
4. Which runtime consumer needs it?
5. Does that consumer need raw configuration, a narrow policy, or an already
   resolved domain value?
6. Is the contract shared by independent siblings, or should it remain beside
   one consumer?

If these questions are answered explicitly, ocint can keep one convenient
daemon configuration file without creating either a global config god object
or a protocol dumping ground.

## Upstream references

- Root schema composition: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/core/src/v1/config/config.ts#L3-L18
- Config service interface: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/config/config.ts#L117-L137
- Global and project source merging: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/config/config.ts#L398-L410
- Instance-scoped config state: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/config/config.ts#L600-L608
- Directory-keyed state cache: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/effect/instance-state.ts#L26-L50
- Provider domain service: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/provider/provider.ts#L1148-L1172
- Broad config dependency in LLM: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/session/llm.ts#L95-L103
- Broad config parameter in overflow logic: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/session/overflow.ts#L8-L19
