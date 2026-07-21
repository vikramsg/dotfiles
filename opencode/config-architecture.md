# OpenCode Configuration Architecture

## Scope

This note explains how OpenCode supports one merged `config.json` document
without making that document an unqualified process-global variable. It also
identifies the places where OpenCode still couples modules to the complete
configuration model.

The source analysis is pinned to OpenCode commit
`849c2598abc7d2b40261e74b5826bc74ffc78308`. Every code excerpt below links to
the exact lines in that revision. Documentation pages are not used as evidence.

## Summary

OpenCode uses four boundaries:

```text
config files
    |
    v
ConfigV1.Info schema             external document contract
    |
    v
Config.Service                   loading, validation, merging and updates
    |
    v
directory-keyed InstanceState    project-specific resolved configuration
    |
    v
Agent / Provider / MCP services  runtime domain APIs
```

The important qualification is that this is not complete decoupling. Agent,
Provider, LLM, MCP, and session code still import either `Config.Service` or
`ConfigV1.Info`. OpenCode replaces an ambient singleton with explicit service
requirements and instance-scoped state, then hides much of the configuration
behind domain services. That localizes coupling; it does not remove it.

## One Schema, Composed From Feature Schemas

The top-level schema is an aggregate at the external boundary. It imports
feature-owned schemas instead of redefining every nested object in one file:

```ts
import { ConfigAgentV1 } from "./agent"
import { ConfigAttachmentV1 } from "./attachment"
import { ConfigCommandV1 } from "./command"
import { ConfigFormatterV1 } from "./formatter"
import { ConfigLayoutV1 } from "./layout"
import { ConfigLSPV1 } from "./lsp"
import { ConfigMCPV1 } from "./mcp"
import { ConfigPermissionV1 } from "./permission"
import { ConfigPluginV1 } from "./plugin"
import { ConfigProviderV1 } from "./provider"
import { ConfigServerV1 } from "./server"
import { ConfigSkillsV1 } from "./skills"
```

Source: [S1]

`ConfigV1.Info` then composes those schemas into the user-facing document. For
example, agents, providers, MCP servers, formatters, and LSP servers remain
separate schemas even though users configure them in one JSON object:

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
mcp: Schema.optional(
  Schema.Record(Schema.String, Schema.Union([ConfigMCPV1.Info, Schema.Struct({ enabled: Schema.Boolean })])),
).annotate({ description: "MCP (Model Context Protocol) server configurations" }),
formatter: Schema.optional(ConfigFormatterV1.Info).annotate({
  description:
    "Enable or configure formatters. Omit or set to false to disable, true to enable built-ins, or an object to enable built-ins with overrides.",
}),
lsp: Schema.optional(ConfigLSPV1.Info).annotate({
  description:
    "Enable or configure LSP servers. Omit or set to false to disable, true to enable built-ins, or an object to enable built-ins with overrides.",
}),
```

Source: [S2]

This is the first modularity mechanism: the root configuration owns document
composition, while nested formats can evolve in focused files.

## Config Is An Injected Service

The runtime config module exposes an interface and an Effect context service:

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

Source: [S3]

The implementation obtains filesystem, authentication, account, environment,
package-management, and HTTP services from the Effect context. Those
dependencies are explicit in the layer rather than constructed by consumers:

```ts
const fs = yield* FSUtil.Service
const authSvc = yield* Auth.Service
const accountSvc = yield* Account.Service
const env = yield* Env.Service
const npmSvc = yield* Npm.Service
const http = yield* HttpClient.HttpClient
```

Source: [S4]

The exported node also declares the concrete dependencies needed to build the
service:

```ts
export const node = LayerNode.make({
  service: Service,
  layer: layer,
  deps: [FSUtil.node, Auth.node, Account.node, Env.node, Npm.node, httpClient],
})
```

Source: [S5]

Consequently, modules depend on the `Config.Service` contract and the
application layer graph supplies its implementation. This is still a broad
service contract, but it is not an unreplaceable imported object holding
mutable process-global data.

## Global Files And Project Overrides

OpenCode creates a minimal global file containing the schema URL when no global
config exists and no environment override redirects configuration:

```ts
if (!Flag.OPENCODE_CONFIG && !Flag.OPENCODE_CONFIG_DIR && !Flag.OPENCODE_CONFIG_CONTENT) {
  const file = globalConfigFile()
  if (!existsSync(file)) {
    yield* fs
      .writeWithDirs(file, JSON.stringify({ $schema: "https://opencode.ai/config.json" }, null, 2))
      .pipe(Effect.catch(() => Effect.void))
  }
}
```

Source: [S6]

It then merges legacy `config.json`, `opencode.json`, and `opencode.jsonc` from
the global config directory in order:

```ts
result = mergeConfig(result, yield* loadFile(path.join(Global.Path.config, "config.json"), env))
result = mergeConfig(result, yield* loadFile(path.join(Global.Path.config, "opencode.json"), env))
result = mergeConfig(result, yield* loadFile(path.join(Global.Path.config, "opencode.jsonc"), env))
```

Source: [S7]

For an active project, the loader starts with global config and then merges an
explicit config path and discovered project files. Therefore "global" describes
a configuration source and precedence level, not the lifetime of one mutable
JavaScript object:

```ts
const global = Object.keys(authEnv).length ? yield* loadGlobal(authEnv) : yield* getGlobal()
yield* merge(Global.Path.config, global, "global")

if (Flag.OPENCODE_CONFIG) {
  yield* merge(Flag.OPENCODE_CONFIG, yield* loadFile(Flag.OPENCODE_CONFIG, authEnv))
  yield* Effect.logDebug("loaded custom config", { path: Flag.OPENCODE_CONFIG })
}

if (!Flag.OPENCODE_DISABLE_PROJECT_CONFIG) {
  for (const file of yield* ConfigPaths.files("opencode", ctx.directory, ctx.worktree).pipe(Effect.orDie)) {
    yield* merge(file, yield* loadFile(file, authEnv), "local")
  }
}
```

Source: [S8]

## Resolved Config Is Instance-Scoped

`Config.Service` puts resolved state in `InstanceState` and its public `get`
operation selects the config from that state:

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

Source: [S9]

`InstanceState` is a scoped cache keyed by the active instance directory. It
initializes entries from the current `InstanceContext` and invalidates the
matching directory when that instance is disposed:

```ts
const cache = yield* ScopedCache.make<string, A, E, R>({
  capacity: Number.POSITIVE_INFINITY,
  lookup: () =>
    Effect.gen(function* () {
      return yield* init(yield* context)
    }),
})

const off = registerDisposer((directory) => Effect.runPromise(ScopedCache.invalidate(cache, directory)))
```

Source: [S10]

Reads use the current instance directory as the cache key:

```ts
export const get = <A, E, R>(self: InstanceState<A, E, R>) =>
  Effect.gen(function* () {
    return yield* ScopedCache.get(self.cache, yield* directory)
  })
```

Source: [S11]

This prevents two active projects from accidentally sharing one resolved
configuration merely because they run in the same server process.

## Domain Services Hide Config From Their Callers

Subsystems usually expose runtime models and operations rather than returning
raw config fragments. `Provider`, for example, owns its resolved runtime
`Info` schema and service interface:

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

Source: [S12]

The provider implementation itself consumes `Config.Service` while callers can
depend on `Provider.Service`. Its provider catalog and SDK state are also
instance-scoped:

```ts
const fs = yield* FSUtil.Service
const config = yield* Config.Service
const auth = yield* Auth.Service
const env = yield* Env.Service
const plugin = yield* Plugin.Service
const modelsDevSvc = yield* ModelsDev.Service
const runtimeFlags = yield* RuntimeFlags.Service

const state = yield* InstanceState.make<State>(() =>
  Effect.gen(function* () {
    const bridge = yield* EffectBridge.make()
    const cfg = yield* config.get()
```

Source: [S13]

Likewise, an LLM stream receives resolved `Provider.Model` and `Agent.Info`
objects in its input instead of model and agent config fragments:

```ts
export type StreamInput = {
  user: SessionV1.User
  sessionID: string
  parentSessionID?: string
  model: Provider.Model
  agent: Agent.Info
  permission?: PermissionV1.Ruleset
  system: string[]
  messages: ModelMessage[]
  small?: boolean
  tools: Record<string, Tool>
  retries?: number
  toolChoice?: "auto" | "required" | "none"
}
```

Source: [S14]

This is the main anti-coupling pattern: a subsystem reads the aggregate config
while building its state, then presents domain-owned types and behavior to the
rest of the application.

## Where Strong Coupling Remains

OpenCode does not follow this pattern consistently enough to claim that modules
are independent of the global model.

The Agent layer imports and obtains the full config service, then reads global
permissions and references while constructing agents:

```ts
const config = yield* Config.Service
const auth = yield* Auth.Service
const plugin = yield* Plugin.Service
const skill = yield* Skill.Service
const provider = yield* Provider.Service
const locations = yield* LocationServiceMap.Service

const state = yield* InstanceState.make<State>(
  Effect.fn("Agent.state")(function* (ctx) {
    const cfg = yield* config.get()
```

Source: [S15]

The LLM service also declares `Config.Service` as a layer requirement and reads
the complete resolved config during each run, despite already receiving agent
and model domain objects:

```ts
const [language, cfg, item, info] = yield* Effect.all(
  [
    provider.getLanguage(input.model),
    config.get(),
    provider.getProvider(input.model.providerID),
    auth.get(input.model.providerID),
  ],
  { concurrency: "unbounded" },
)
```

Source: [S16]

Some lower-level session helpers accept the broad config type directly. The
overflow calculation only needs compaction settings, but its parameter is
`ConfigV1.Info`:

```ts
export function usable(input: { cfg: ConfigV1.Info; model: Provider.Model; outputTokenMax?: number }) {
  const context = input.model.limit.context
  if (context === 0) return 0

  const reserved =
    input.cfg.compaction?.reserved ??
    Math.min(COMPACTION_BUFFER, ProviderTransform.maxOutputTokens(input.model, input.outputTokenMax))
```

Source: [S17]

MCP similarly derives a nested type by indexing into the root config type:

```ts
type McpEntry = NonNullable<ConfigV1.Info["mcp"]>[string]
```

Source: [S18]

These examples are genuine compile-time coupling. Renaming or restructuring
root config fields can require edits in these modules. Effect service injection
improves lifecycle, replacement, and dependency visibility, but it does not by
itself narrow the dependency.

## Architectural Assessment

OpenCode's approach works because it separates three concerns that are often
incorrectly called "global config":

- The JSON schema is one external contract composed from feature schemas.
- `Config.Service` is an injected loader and persistence API.
- The resolved value is cached per project directory, not once per process.

Its domain services then absorb much of the translation from configuration to
runtime objects. This permits callers to ask `Provider.Service` for a model or
`Agent.Service` for an agent without understanding config discovery and merge
precedence.

The tradeoff is pragmatic rather than pure. Subsystem initialization commonly
depends on the whole config service, and several helpers depend on the root
`ConfigV1.Info` type. OpenCode has modular runtime APIs around a shared external
schema; it does not have fully isolated modules with narrow configuration
ports.

For code requiring stricter dependency inversion, retain OpenCode's composed
schema and instance-scoped lifecycle but map the root document at the
composition boundary:

```text
ConfigV1.Info
    |
    +--> AgentSettings     --> Agent.Service
    +--> ProviderSettings  --> Provider.Service
    +--> CompactionPolicy  --> overflow calculations
    +--> McpSettings       --> MCP.Service
```

That variation prevents feature code from importing the aggregate config type
while preserving a single validated user configuration file.

## Source References

- [S1] Config schema imports: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/core/src/v1/config/config.ts#L3-L18
- [S2] Feature schema composition: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/core/src/v1/config/config.ts#L90-L123
- [S3] Config service interface: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/config/config.ts#L117-L137
- [S4] Config implementation dependencies: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/config/config.ts#L175-L184
- [S5] Config layer dependencies: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/config/config.ts#L675-L679
- [S6] Global config creation: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/config/config.ts#L246-L257
- [S7] Global config merge order: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/config/config.ts#L258-L260
- [S8] Global and project merge: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/config/config.ts#L398-L410
- [S9] Config instance state and getter: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/config/config.ts#L600-L608
- [S10] Scoped instance cache and disposal: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/effect/instance-state.ts#L26-L45
- [S11] Directory-keyed instance read: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/effect/instance-state.ts#L47-L50
- [S12] Provider service interface: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/provider/provider.ts#L1148-L1172
- [S13] Provider config dependency and instance state: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/provider/provider.ts#L1327-L1343
- [S14] LLM stream domain input: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/session/llm.ts#L35-L48
- [S15] Agent config dependency: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/agent/agent.ts#L88-L101
- [S16] LLM config read: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/session/llm.ts#L95-L103
- [S17] Broad config type in overflow calculation: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/session/overflow.ts#L8-L19
- [S18] Root config type indexed by MCP: https://github.com/anomalyco/opencode/blob/849c2598abc7d2b40261e74b5826bc74ffc78308/packages/opencode/src/mcp/index.ts#L109-L120
