# How OpenCode Contains a Global Configuration

OpenCode has a global configuration file, but the file is not itself a global
object imported by every module. The implementation turns configuration into an
Effect service, scopes its resolved value to a project instance, and lets domain
services translate the broad input schema into narrower runtime models.

This article studies upstream OpenCode at commit
[`909db63265971d67d2fe4ba7f9d7b74cc33e2fdc`](https://github.com/anomalyco/opencode/tree/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc)
from 2026-07-24. All citations point to source code at that immutable revision,
not to OpenCode documentation.

## The short answer

There are three different things that are easy to call "the global config":

1. **A global file:** `~/.config/opencode/config.json`, `opencode.json`, or
   `opencode.jsonc` is one input layer.
2. **A broad input model:** `ConfigV1.Info` validates the user-facing shape.
3. **A runtime service:** `Config.Service` resolves and exposes configuration
   through an interface supplied by the application's Effect layer.

The design reduces coupling by centralizing file I/O, parsing, precedence, and
caching; by scoping the merged result to an `InstanceContext`; and by exposing
domain services such as `Agent.Service` and `Provider.Service` to most downstream
callers.

It does **not** remove configuration coupling. Agent, provider, LSP, MCP, session,
and other feature modules directly import the `Config` module and declare
`Config.node` as a dependency. This is service-locator-style dependency access
inside an explicit dependency graph, not pure constructor injection and not a
collection of completely config-agnostic modules. The important achievement is
that these modules depend on a replaceable service interface rather than reading
JSON files, environment variables, or a mutable singleton themselves.

## End-to-end flow

```text
 Configuration inputs
 +----------------------+   +----------------------+   +---------------------+
 | remote / managed     |   | ~/.config/opencode  |   | project .opencode   |
 | environment overrides|   | global files         |   | files and Markdown  |
 +----------+-----------+   +----------+-----------+   +----------+----------+
            |                          |                          |
            +--------------------------+--------------------------+
                                       |
                                       v
                         +-----------------------------+
                         | Config service              |
                         | substitute -> parse/schema  |
                         | -> merge by precedence      |
                         +--------------+--------------+
                                        |
                         cached by instance directory
                                        |
                  +---------------------+---------------------+
                  |                                           |
                  v                                           v
        +--------------------+                       +--------------------+
        | Agent service      |                       | Provider service   |
        | Config -> Agent.Info|                       | Config -> Provider |
        | permissions/defaults|                      | model catalog/SDK  |
        +---------+----------+                       +----------+---------+
                  |                                             |
                  +----------------------+----------------------+
                                         |
                                         v
                         sessions, tools, HTTP handlers, TUI
```

The input and merge stages are implemented in
[`config.ts` lines 213-237](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/config/config.ts#L213-L237)
and
[`config.ts` lines 314-475](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/config/config.ts#L314-L475).
Per-directory caching comes from
[`instance-state.ts` lines 26-57](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/effect/instance-state.ts#L26-L57).
Agent and provider materialization appears in
[`agent.ts` lines 88-119](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/agent/agent.ts#L88-L119)
and
[`provider.ts` lines 1327-1384](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/provider/provider.ts#L1327-L1384).

## 1. The JSON file is an adapter, not the domain API

The global loader knows file names and precedence. Feature modules do not.
OpenCode merges the legacy `config.json`, then `opencode.json`, then
`opencode.jsonc`:

```ts
result = mergeConfig(result, yield* loadFile(path.join(Global.Path.config, "config.json"), env))
result = mergeConfig(result, yield* loadFile(path.join(Global.Path.config, "opencode.json"), env))
result = mergeConfig(result, yield* loadFile(path.join(Global.Path.config, "opencode.jsonc"), env))
```

Source:
[`packages/opencode/src/config/config.ts` lines 258-260](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/config/config.ts#L258-L260).

Loading is also the single validation boundary. Variable substitution happens
before JSONC parsing, and the parsed value is decoded with `ConfigV1.Info`:

```ts
const expanded = yield* Effect.promise(() =>
  ConfigVariable.substitute(
    "path" in options
      ? { text, type: "path", path: options.path, env }
      : { text, type: "virtual", ...options, env },
  ),
)
const parsed = ConfigParse.jsonc(expanded, source)
const data = ConfigParse.schema(ConfigV1.Info, normalizeLoadedConfig(parsed), source)
```

Source:
[`packages/opencode/src/config/config.ts` lines 218-228](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/config/config.ts#L218-L228).

This creates a useful boundary: changing JSONC parsing, variable syntax, file
discovery, or configuration precedence does not require corresponding parsing
logic in providers, agents, or tools.

## 2. One schema is broad, but it is assembled from feature schemas

`ConfigV1.Info` is intentionally an application-wide input schema. It delegates
feature-shaped fields to schemas owned by those features rather than spelling
every nested shape in one hand-written TypeScript interface:

```ts
agent: Schema.optional(
  Schema.StructWithRest(
    Schema.Struct({
      plan: Schema.optional(ConfigAgentV1.Info),
      build: Schema.optional(ConfigAgentV1.Info),
      general: Schema.optional(ConfigAgentV1.Info),
      explore: Schema.optional(ConfigAgentV1.Info),
      title: Schema.optional(ConfigAgentV1.Info),
      summary: Schema.optional(ConfigAgentV1.Info),
      compaction: Schema.optional(ConfigAgentV1.Info),
    }),
    [Schema.Record(Schema.String, ConfigAgentV1.Info)],
  ),
).annotate({ description: "Agent configuration, see https://opencode.ai/docs/agents" }),
provider: Schema.optional(Schema.Record(Schema.String, ConfigProviderV1.Info)).annotate({
  description: "Custom provider configurations and model overrides",
}),
```

Source:
[`packages/core/src/v1/config/config.ts` lines 96-112](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/core/src/v1/config/config.ts#L96-L112).

The agent config schema itself owns normalization of deprecated tool flags,
extension options, and `maxSteps`:

```ts
const normalize = (agent: Schema.Schema.Type<typeof AgentSchema>): Schema.Schema.Type<typeof AgentSchema> => {
  const options: Record<string, unknown> = { ...agent.options }
  for (const [key, value] of Object.entries(agent)) {
    if (!KNOWN_KEYS.has(key)) options[key] = value
  }

  const permission: ConfigPermissionV1.Info = {}
  for (const [tool, enabled] of Object.entries(agent.tools ?? {})) {
    const action = enabled ? "allow" : "deny"
    if (tool === "write" || tool === "edit" || tool === "patch") {
      permission.edit = action
      continue
    }
    permission[tool] = action
  }
  globalThis.Object.assign(permission, agent.permission)

  const steps = agent.steps ?? agent.maxSteps
  return { ...agent, options, permission, ...(steps !== undefined ? { steps } : {}) }
}
```

Source:
[`packages/core/src/v1/config/agent.ts` lines 62-81](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/core/src/v1/config/agent.ts#L62-L81).

This is modular schema composition, not independent configuration models. The
top-level schema still imports every nested config schema, which is appropriate
for a serialization boundary but would be undesirable as every module's runtime
API.

## 3. Runtime access is behind a service contract

The key indirection is `Config.Interface`. Consumers request an Effect that
produces config; they do not import an eagerly initialized object:

```ts
export interface Interface {
  readonly get: () => Effect.Effect<Info>
  readonly getGlobal: () => Effect.Effect<Info>
  readonly getConsoleState: () => Effect.Effect<ConsoleState>
  readonly update: (config: Info) => Effect.Effect<void>
  readonly updateGlobal: (config: Info) => Effect.Effect<{ info: Info; changed: boolean }>
  readonly invalidate: () => Effect.Effect<void>
  readonly directories: () => Effect.Effect<string[]>
  readonly waitForDependencies: () => Effect.Effect<void>
}

export class Service extends Context.Service<Service, Interface>()("@opencode/Config") {}
```

Source:
[`packages/opencode/src/config/config.ts` lines 124-137](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/config/config.ts#L124-L137).

The production implementation is wired at the composition root alongside the
rest of the service graph:

```ts
export const AppLayer = AppNodeBuilderV1.build(
  LayerNode.group([
    Npm.node,
    FSUtil.node,
    Database.node,
    Auth.node,
    Account.node,
    Config.node,
    Git.node,
    Storage.node,
    Snapshot.node,
    Plugin.node,
    ModelsDev.node,
    Provider.node,
    ProviderAuth.node,
    Agent.node,
```

Source:
[`packages/opencode/src/effect/app-runtime.ts` lines 58-73](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/effect/app-runtime.ts#L58-L73).

This makes dependency construction explicit and permits another implementation
of `Config.Interface`. It does not make the dependency invisible: a feature that
imports `Config.Service` is still coupled to the broad config contract.

## 4. "Global" values become instance-scoped values

OpenCode can serve more than one directory in a process. The context that
distinguishes them is small:

```ts
export interface InstanceContext {
  directory: string
  worktree: string
  project: Project.Info
}
```

Source:
[`packages/opencode/src/project/instance-context.ts` lines 5-9](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/project/instance-context.ts#L5-L9).

`InstanceState` uses that context's directory as the cache key. Therefore a
single service object can safely expose different resolved state for different
projects:

```ts
const cache = yield* ScopedCache.make<string, A, E, R>({
  capacity: Number.POSITIVE_INFINITY,
  lookup: () =>
    Effect.gen(function* () {
      return yield* init(yield* context)
    }),
})
```

Source:
[`packages/opencode/src/effect/instance-state.ts` lines 26-36](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/effect/instance-state.ts#L26-L36).

The config service stores not just the merged config but its directories,
background dependency fibers, and console state per instance. `get()` selects
the current instance's config:

```ts
const state = yield* InstanceState.make<State>(
  Effect.fn("Config.state")(function* (ctx) {
    return yield* loadInstanceState(ctx).pipe(Effect.orDie)
  }),
)

const get = Effect.fn("Config.get")(function* () {
  return yield* InstanceState.use(state, (s) => s.config)
})
```

Source:
[`packages/opencode/src/config/config.ts` lines 600-608](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/config/config.ts#L600-L608).

This is the most important correction to the phrase "global model": the global
file participates in every instance's merge, but the effective runtime config is
not one process-wide mutable value.

## 5. Domain services absorb the broad model

The agent module does read config directly when it builds its state. It then
maps serialized fields into its own runtime `Agent.Info`: model strings are
parsed, snake-case `top_p` becomes `topP`, and permissions are converted and
merged:

```ts
if (value.model) item.model = Provider.parseModel(value.model)
item.variant = value.variant ?? item.variant
item.prompt = value.prompt ?? item.prompt
item.description = value.description ?? item.description
item.temperature = value.temperature ?? item.temperature
item.topP = value.top_p ?? item.topP
item.mode = value.mode ?? item.mode
item.color = value.color ?? item.color
item.hidden = value.hidden ?? item.hidden
item.name = value.name ?? item.name
item.steps = value.steps ?? item.steps
item.options = mergeDeep(item.options, value.options ?? {})
item.permission = Permission.merge(item.permission, Permission.fromConfig(value.permission ?? {}))
```

Source:
[`packages/opencode/src/agent/agent.ts` lines 281-293](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/agent/agent.ts#L281-L293).

Downstream callers can depend on the narrower agent contract rather than the
shape of `config.agent`:

```ts
export interface Interface {
  readonly get: (agent: string) => Effect.Effect<Info>
  readonly list: () => Effect.Effect<Info[]>
  readonly defaultInfo: () => Effect.Effect<Info>
  readonly defaultAgent: () => Effect.Effect<string>
  readonly generate: (input: {
    description: string
    model?: { providerID: ProviderV2.ID; modelID: ModelV2.ID }
  }) => Effect.Effect<
    {
      identifier: string
      whenToUse: string
      systemPrompt: string
    },
    Provider.DefaultModelError
  >
}
```

Source:
[`packages/opencode/src/agent/agent.ts` lines 64-80](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/agent/agent.ts#L64-L80).

Provider follows the same pattern. Its public interface speaks in provider IDs,
model IDs, runtime models, and language-model clients, not raw JSON sections:

```ts
export interface Interface {
  readonly list: () => Effect.Effect<Record<ProviderV2.ID, Info>>
  readonly getProvider: (providerID: ProviderV2.ID) => Effect.Effect<Info>
  readonly getModel: (providerID: ProviderV2.ID, modelID: ModelV2.ID) => Effect.Effect<Model, ModelNotFoundError>
  readonly getLanguage: (model: Model) => Effect.Effect<LanguageModelV3, ModelNotFoundError>
  readonly closest: (
    providerID: ProviderV2.ID,
    query: string[],
  ) => Effect.Effect<{ providerID: ProviderV2.ID; modelID: string } | undefined>
  readonly getSmallModel: (providerID: ProviderV2.ID) => Effect.Effect<Model | undefined>
  readonly defaultModel: () => Effect.Effect<{ providerID: ProviderV2.ID; modelID: ModelV2.ID }, DefaultModelError>
}
```

Source:
[`packages/opencode/src/provider/provider.ts` lines 1148-1159](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/provider/provider.ts#L1148-L1159).

This translation layer is what prevents serialization details from spreading
indefinitely. A session that asks `Provider.Service` for a model does not need to
know whether it came from a global JSON file, project JSONC, environment content,
a plugin, a remote organization config, or the built-in model catalog.

## 6. Replaceability is demonstrated in tests

The service interface is not ceremony around a fixed singleton. OpenCode's test
fixture constructs a complete fake and installs it as an Effect layer:

```ts
export function make(overrides: Partial<Config.Interface> = {}) {
  return Config.Service.of({
    get: () => Effect.succeed({}),
    getGlobal: () => Effect.succeed({}),
    getConsoleState: () => Effect.succeed(emptyConsoleState),
    update: () => Effect.void,
    updateGlobal: (config) => Effect.succeed({ info: config, changed: false }),
    invalidate: () => Effect.void,
    directories: () => Effect.succeed([]),
    waitForDependencies: () => Effect.void,
    ...overrides,
  })
}

export function layer(overrides?: Partial<Config.Interface>) {
  return Layer.succeed(Config.Service, make(overrides))
}
```

Source:
[`packages/opencode/test/fixture/config.ts` lines 5-20](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/test/fixture/config.ts#L5-L20).

That is a concrete benefit of depending on `Config.Service`: tests can supply a
small deterministic implementation without creating home-directory files or
changing process-global configuration.

## Where coupling still exists

The architecture contains coupling; it does not abolish it.

| Boundary | What is decoupled | What remains coupled |
| --- | --- | --- |
| File loader | Features do not parse JSONC or discover files | `Config` knows every input source and precedence rule |
| Schema composition | Nested agent/provider schemas live in feature files | `ConfigV1.Info` imports the complete application schema |
| Effect service | Implementation and test fake are replaceable | Consumers importing `Config.Service` know the broad interface |
| Instance state | No single effective config leaks across directories | Directory identity is ambient through `InstanceRef` |
| Domain services | Callers use `Agent.Info`, `Provider.Model`, and service methods | Agent and provider initialization still read `Config.Info` |

The dependency is visible in the production graph. For example, Agent declares
both the narrow services it uses and `Config.node`:

```ts
export const node = LayerNode.make({
  service: Service,
  layer: layer,
  deps: [Config.node, Auth.node, Plugin.node, Skill.node, Provider.node, locationServiceMapNode],
})
```

Source:
[`packages/opencode/src/agent/agent.ts` lines 447-451](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/agent/agent.ts#L447-L451).

This is a pragmatic tradeoff. Configuration is inherently a cross-cutting input,
and OpenCode accepts direct config dependencies in modules that materialize or
apply configuration. The stronger boundary is one layer farther downstream:
callers should ask Agent, Provider, Permission, LSP, or MCP for behavior rather
than repeatedly interpreting `Config.Info` themselves.

## Reusable design rules

The implementation suggests a practical pattern for applications with one large
user configuration:

1. Keep all file, environment, remote, and precedence rules in one adapter.
2. Validate once into a typed input model at that boundary.
3. Expose access through a replaceable service contract, not an exported mutable
   object.
4. Scope the resolved value by the real unit of isolation, such as project or
   tenant, even when one input file is called global.
5. Let each domain service translate its config subsection into runtime types and
   defaults.
6. Make downstream modules depend on domain behavior, not raw config fields.
7. Keep dependencies explicit in the composition graph and test them with
   replacement layers.
8. Be honest about the remaining broad dependency. If too many modules need
   `Config.Service`, split read capabilities into smaller interfaces rather than
   pretending the global model is gone.

The result is not "no global configuration." It is a global configuration kept
at the system boundary, resolved per instance, and progressively converted into
domain-owned runtime APIs.
