# ocint daemon protocol-first rearchitecture

## Goal

Make `ocint.daemon.models` the small, stable contract seam for daemon-wide
vocabulary. Consumers should depend on read-only protocols, while API, config,
database, Git, and OpenCode boundaries retain the concrete types they validate
or construct.

This is not a move of every class or every `Protocol` into `models.py`. The
migration should remove `service.py` as the accidental schema hub without
creating a new hub with the same problem.

The companion
[OpenCode configuration lessons](bin/ocint/docs/architecture/opencode-config-lessons.md)
note explains how one aggregate external config can support this modular shape
without becoming a runtime god object.

## Current problem

`ocint/daemon/service.py` currently owns four different concerns:

1. Job vocabulary: `JobState`, `JobStage`, `WorkRequest`, `Job`, `Worktree`, and
   `PromptObservation`.
2. Persistence commands: eight checkpoint models and the `Checkpoint` union.
3. Consumer ports: `JobStore`, `OpenCode`, `Git`, and `GitHub`.
4. Business rules and execution: authorization, prompt decisions, command
   rendering, and `JobExecutor`.

This makes adapters import the workflow implementation merely to exchange
data:

```text
API -----------+
repository ----+
Git -----------+----> service.py <---- config.py
OpenCode ------+
tasks ---------+
GitHub --------+
```

The coupling is visible in production imports:

- `api.py` imports `Job` and `WorkRequest` from `service.py`.
- `repository.py` imports the job models and all checkpoint classes from
  `service.py`.
- `git.py` imports `Worktree` from `service.py`.
- `opencode.py` imports `PromptObservation` from `service.py`.
- `tasks/run.py`, `tasks/repository.py`, and `github/service.py` import job
  types from `service.py`.

`ocint/daemon/models.py` currently contains only the read-only `LogRotation`
protocol. That is the direction to extend, but only for genuinely daemon-wide
contracts.

## Target shape

```text
                     daemon/models.py
                  enums + narrow protocols
                            ^
                            |
       +--------------------+--------------------+
       |                    |                    |
 API boundary         service workflow     repository boundary
 Pydantic payloads    consumer-owned ports  concrete stored records
       |                    |                    |
       +--------------------+--------------------+
                            |
                 Git / OpenCode / GitHub
                 adapter-owned concrete data
```

Dependencies point toward contracts. Concrete Pydantic models do not move
inward merely to avoid declaring a small boundary mapping.

## `models.py` admission rule

A declaration belongs in `ocint/daemon/models.py` only when all of these are
true:

- It names stable daemon vocabulary rather than a transport, database,
  framework, renderer, or one-workflow detail.
- It has independent consumers in sibling daemon areas, not merely one
  consumer and its implementation.
- Its fields and meaning are expected to change together across those
  consumers.
- It can be declared without importing config implementations, FastAPI,
  Pydantic, SQLAlchemy, aiohttp, GitHub payloads, task models, or LCH models.
- A read-only protocol or shared enum is sufficient; runtime validation and
  construction remain with the owning boundary.

Import count alone is not an admission criterion. Before adding a declaration,
the change must identify its owner, consumers, lifecycle, and reason it cannot
remain local.

### Initial contents

The first migration should keep the file intentionally small:

| Declaration | Form | Reason |
| --- | --- | --- |
| `JobState` | `StrEnum` | Closed job lifecycle vocabulary used by execution, persistence, API/task coordination, and integrations. |
| `JobStage` | `StrEnum` | Closed execution-stage vocabulary shared by the same lifecycle. |
| `WorkRequest` | read-only `Protocol` | Command data enters through API, CLI, and task boundaries and is consumed by execution and persistence. |
| `Job` | read-only `Protocol` | Durable job view consumed by execution, API, tasks, and GitHub behavior. |
| `Worktree` | read-only `Protocol` | Stable value exchanged between job execution and Git without exposing the Git adapter's concrete result. |
| `RepositoryPolicy` | read-only `Protocol` | The job workflow and Git/GitHub behavior need the same resolved repository policy without depending on `RepositoryConfig`. |
| `LogRotation` | read-only `Protocol` | Existing stable logging policy contract implemented structurally by `LoggingConfig`. |

Use `@property` members on protocols. Mutable protocol attributes are invariant
and would make structural conformance with frozen boundary models needlessly
fragile.

`PromptObservation` should initially be a service-owned protocol because it is
specific to the executor's OpenCode decision and has only one consumer.
Promote it only if another independent daemon workflow adopts the same meaning.

### Explicit exclusions

Do not place these in root `models.py`:

- `JobStore`, `OpenCode`, `Git`, and `GitHub`: these ports are owned by
  `JobExecutor`, their consumer, and stay in `service.py`.
- `JobQueries`: API-local query capability.
- `IdleExecutor` and `IdleTasks`: `run.py` workflow capabilities.
- `ThreadSource` and `TaskExecutor`: task-workflow capabilities.
- `GitHubTransport`: GitHub-service capability.
- `CommandRunner` and `SqliteConnection`: infrastructure-local capabilities.
- FastAPI request/response models and OpenCode/GitHub wire payloads.
- SQL row models, checkpoint persistence representations, and migration data.
- `DaemonConfig`, settings, contexts, secrets, paths, and concrete policy
  models.
- Task/thread models, LCH discovery and diagnostics, renderer values, or
  logging implementation details.
- Functions, factories, validators, mappings, I/O, or business rules.

## Concrete ownership after migration

| Owner | Concrete declarations and behavior |
| --- | --- |
| `daemon/api.py` | FastAPI request payload and response models; map request payloads to the `WorkRequest` contract and `Job` views to responses. |
| `daemon/config.py` | Pydantic settings and resolved config, including concrete repository policy validation. |
| `daemon/repository.py` | Concrete immutable stored-job record built from SQL rows and all SQL persistence mapping. |
| `daemon/git.py` | Concrete immutable worktree result constructed after Git operations. |
| `daemon/opencode.py` | OpenCode wire payloads and concrete prompt observation. |
| `daemon/tasks/models.py` | Thread/message/task lifecycle models; add a task-owned concrete work request if task construction requires one. |
| `daemon/service.py` | Job business rules, execution workflow, and consumer-owned ports. |
| `daemon/github/models.py` | GitHub integration payload and persistence models; do not merge these with LCH's similarly named models. |

The CLI remains the composition root. It may construct a small CLI-owned
immutable request value, or use an exported application command constructor if
one later has a demonstrated non-framework owner. It must not use the HTTP
payload merely because the fields happen to match.

## Migration phases

Each phase should be a reviewable change that preserves daemon behavior. Do not
add compatibility re-exports from `service.py`; update callers in the same
phase so the old ownership cannot persist.

### Phase 1: Establish architecture guards

1. Extend `tests/architecture/test_daemon_architecture.py` to parse
   `daemon/models.py` and assert it contains only enums, protocols, and type
   aliases, with no top-level functions or runtime model classes.
2. Prohibit imports in `daemon/models.py` from `ocint.daemon` implementation
   modules and from Pydantic, FastAPI, SQLAlchemy, aiohttp, uvicorn, and other
   adapter frameworks.
3. Add an import-direction assertion that production modules outside
   `service.py` do not import data declarations from `service.py`.
4. Keep tests structural rather than asserting an exhaustive symbol list. The
   admission policy should prevent wrong dependencies without making every
   legitimate contract change require a brittle allowlist update.
5. Preserve the existing checks that logging uses `LogRotation`, task core is
   provider-neutral, and configuration loading stays in `config.py`.

### Phase 2: Introduce shared protocols and enums

1. Move `JobState` and `JobStage` to `daemon/models.py`.
2. Define read-only `WorkRequest`, `Job`, `Worktree`, and `RepositoryPolicy`
   protocols from the fields consumers actually read. Do not mechanically copy
   every field from the current Pydantic classes.
3. Audit each consumer before adding a protocol member. For example, API output
   does not justify exposing fields used only by repository reconstruction.
   The `Job` protocol is the union of stable job facts required by independent
   consumers, not a mirror generated from the jobs table.
4. Keep `LogRotation` unchanged unless static checking identifies a necessary
   variance fix.
5. Run the strict type checker immediately. Confirm that Pydantic fields satisfy
   read-only properties structurally and fix the contract rather than adding
   ignores or runtime protocol checks.

### Phase 3: Localize boundary construction

1. Rename the FastAPI body model to make its boundary explicit, such as
   `WorkRequestPayload`; pass it to the executor through the `WorkRequest`
   protocol.
2. Add a private immutable stored-job model in `repository.py`. Build it in
   `_job()` after converting raw SQL values to `Path`, `JobState`, and
   `JobStage`; return it as `Job` from public repository methods.
3. Add an adapter-owned immutable worktree value in `git.py`; return it as the
   shared `Worktree` protocol.
4. Move the concrete prompt observation into `opencode.py`. Define the minimal
   read-only observation protocol next to the `OpenCode` consumer port in
   `service.py`, so the adapter conforms without importing the service module.
5. Replace task and CLI construction of the old Pydantic `WorkRequest` with
   local immutable values that satisfy the protocol. Keep validation at each
   external boundary and avoid a generic root constructor.
6. Update fakes and fixtures to use test-local concrete values rather than
   importing concrete domain-shaped Pydantic models from `service.py`.

At the end of this phase, `api.py`, `repository.py`, `git.py`, `opencode.py`,
`tasks/`, and `github/` must not import shared data from `service.py`.

### Phase 4: Replace checkpoint DTO coupling

The checkpoint classes are not daemon-wide vocabulary. They exist to let
`JobExecutor` describe SQL mutations and force both the service and repository
to know one persistence command union. Moving that union to root `models.py`
would create the dumping ground this rearchitecture is intended to avoid.

Replace `JobStore.checkpoint(job_id, Checkpoint)` with semantic store methods
owned by the executor port, for example:

```text
record_worktree(job_id, worktree)
record_session(job_id, session_id, server_url)
record_prompt_intent(job_id)
record_prompt_submission(job_id)
advance_stage(job_id, stage)
record_commit(job_id, sha)
record_push(job_id, revision)
record_pull_request(job_id, url)
```

1. Add the semantic methods to `JobStore` and implement them directly in
   `ControlRepository`.
2. Keep the transition-specific SQL updates in `repository.py`; the service
   names intent but does not describe columns.
3. Update executor calls one transition at a time while preserving current
   idempotency and stage side effects.
4. Delete all checkpoint Pydantic classes and the `Checkpoint` union after the
   final caller is migrated.
5. Rewrite repository tests around observable job transitions rather than
   construction and pattern matching of checkpoint DTOs.

This changes an internal API only. It must not alter the jobs schema or require
a database migration.

### Phase 5: Invert concrete config dependencies selectively

1. Change service authorization, Git provisioning, and relevant GitHub policy
   checks to accept `RepositoryPolicy`, while `RepositoryConfig` remains the
   concrete validated implementation.
2. Do not create one protocol that mirrors all of `DaemonConfig`.
3. Keep scheduler and executor settings consumer-local unless a second
   independent consumer needs the exact same policy. If needed, define a narrow
   service-owned execution-policy protocol rather than promoting all daemon
   config to root models.
4. Revisit the architecture test that currently requires `service -> config`.
   Replace it with the intended direction: config constructs concrete policy;
   core behavior reads protocol contracts. Composition code may still import
   both.
5. Verify concrete return types such as `DaemonConfig.repository()` conform
   covariantly to the protocol expected by consumers.

### Phase 6: Clarify package API without creating cycles

1. Decide which daemon operations are supported outside the package before
   changing `daemon/__init__.py`.
2. Do not eagerly re-export repository, adapter, or service implementation
   classes merely to shorten imports.
3. Export only stable operations/contracts with demonstrated external callers.
   Internal sibling modules may import `ocint.daemon.models` directly.
4. Add facade tests only for the deliberately supported API, not every model.

### Phase 7: Remove residue and verify

1. Search production and tests for imports of removed model/checkpoint symbols
   from `service.py`.
2. Confirm `service.py` contains business decisions, execution, and its
   consumer-owned ports, but no boundary Pydantic models or persistence command
   DTOs.
3. Confirm root `models.py` has no adapter payloads, task/LCH/GitHub models,
   concrete config, helper functions, or consumer-local capability protocols.
4. Run focused unit, integration, and end-to-end daemon tests after each phase.
5. Run the package checks at completion:

```sh
just --justfile bin/ocint/justfile test
just --justfile bin/ocint/justfile check
just --justfile bin/ocint/justfile smoke
```

## Required behavioral coverage

The migration is complete only if tests retain coverage for:

- API request validation and response serialization.
- Duplicate submission idempotency and retry inheritance.
- Atomic claim, requeue, recovery, completion, and failure.
- Every persisted job transition formerly represented by a checkpoint.
- Prompt intent/submission recovery behavior.
- Worktree reuse and validation.
- Scheduler capacity, timeouts, cancellation, and shutdown.
- Task initial/follow-up/retry behavior and GitHub completion publication.
- Static conformance of boundary-owned concrete values to shared protocols.
- Import direction and `models.py` declaration-only constraints.

## Non-goals

- No database schema or public HTTP shape change.
- No rewrite of `JobExecutor` behavior while moving contracts.
- No consolidation of historical `ocint/opencode/models.py` with live daemon
  OpenCode payloads; they represent different boundaries and lifecycles.
- No movement of task, GitHub, LCH, logging, API, or SQL types solely because
  they are under the daemon package.
- No broad cleanup of `ctx/models.py` or other model modules in this change.
- No runtime `@runtime_checkable` checks unless a real runtime use appears.
- No compatibility aliases preserving imports from the old owner.

## Completion criteria

- Shared daemon consumers depend on `daemon.models` contracts, not concrete
  adapter/config/service models.
- Every concrete validated model is constructed and owned at an external or
  persistence boundary.
- `service.py` no longer acts as the daemon's schema module.
- `daemon/models.py` remains a short declaration-only module whose members all
  pass the admission rule.
- Checkpoint persistence coupling is replaced by semantic store operations.
- Type checking, architecture tests, unit tests, integration tests, and smoke
  tests pass without ignores or compatibility shims.
