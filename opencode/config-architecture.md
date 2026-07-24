# One Config File, Without One Global Object: OpenCode's Configuration Architecture

OpenCode presents users with one large `config.json` schema. That can look like one
large application-wide model which every feature must import. The implementation is
more nuanced:

1. The published JSON Schema is generated from one *composed schema*.
2. Config files are decoded and merged in one infrastructure module.
3. Runtime consumers request an injected config service rather than importing a
   parsed object.
4. The service resolves the effective config for the current project instance.
5. Feature modules still depend on the broad config type and service, so the design
   reduces global-state coupling; it does not eliminate configuration coupling.

This article examines OpenCode commit
[`909db63265971d67d2fe4ba7f9d7b74cc33e2fdc`](https://github.com/anomalyco/opencode/tree/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc).
All citations below link to code at that immutable commit, not to documentation.

## Three Things Called "Global"

It helps to distinguish three ideas which are easily conflated:

- **Global schema:** one public JSON Schema containing all supported settings.
- **Global file:** a user-level config file in OpenCode's config directory.
- **Global object:** one process-wide mutable object read directly by every module.

OpenCode has the first two. Its normal feature path does not use the third. A feature
gets a service from Effect's context and asks that service for the effective config.
That effective config includes the global file, project files, environment overrides,
remote config, and managed config.

```text
                         build time

 domain schemas        ConfigV1.Info            config.json
 AgentConfig -----+                            (JSON Schema)
 ProviderConfig --+--> composed schema ---------> generated file
 MCPConfig -------+          |
 PermissionConfig +          | runtime validator
                             v
                         runtime

 global file ----+
 project files --+
 env config -----+--> Config service --> per-instance effective Info
 remote config --+          ^                      |
 managed config +           | injected             +--> Agent
                             |                      +--> Provider
                       application Layer           +--> Task tool
                                                    +--> other features
```

Diagram basis: schema composition is visible in
[`packages/core/src/v1/config/config.ts` lines 7-44](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/core/src/v1/config/config.ts#L7-L44),
schema generation in
[`packages/opencode/script/schema.ts` lines 68-76](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/script/schema.ts#L68-L76),
runtime merging in
[`packages/opencode/src/config/config.ts` lines 398-429](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/config/config.ts#L398-L429),
and application composition in
[`packages/opencode/src/effect/app-runtime.ts` lines 58-109](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/effect/app-runtime.ts#L58-L109).

## The Public Schema Is a Composition Root

The top-level schema does not redefine every feature's configuration inline. It
imports schemas owned by configuration domains such as agents, MCP, providers, LSP,
permissions, and plugins:

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

Source: [`packages/core/src/v1/config/config.ts` lines 7-18](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/core/src/v1/config/config.ts#L7-L18).

The aggregate then refers to those schemas at its boundary:

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

Source: [`packages/core/src/v1/config/config.ts` lines 96-112](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/core/src/v1/config/config.ts#L96-L112).

This is schema composition, not a global variable. For example, the agent module owns
its validation, normalization, and inferred `Info` type:

```ts
export const Info = AgentSchema.pipe(
  Schema.decodeTo(AgentSchema, {
    decode: SchemaGetter.transform(normalize),
    encode: SchemaGetter.passthrough({ strict: false }),
  }),
).annotate({ identifier: "AgentConfig" })
export type Info = Schema.Schema.Type<typeof Info>
```

Source: [`packages/core/src/v1/config/agent.ts` lines 83-89](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/core/src/v1/config/agent.ts#L83-L89).

The single `config.json` is generated from that same runtime schema. There is no
second handwritten JSON model to keep synchronized:

```ts
function generateEffect(schema: Schema.Top) {
  const document = Schema.toJsonSchemaDocument(schema)
  const normalized = normalize({
    $schema: "https://json-schema.org/draft/2020-12/schema",
    ...document.schema,
    $defs: document.definitions,
  })
```

Source: [`packages/opencode/script/schema.ts` lines 11-17](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/script/schema.ts#L11-L17).

```ts
await Bun.write(configFile, JSON.stringify(generateEffect(ConfigV1.Info), null, 2))
```

Source: [`packages/opencode/script/schema.ts` line 72](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/script/schema.ts#L72).

The important pattern is **many owning schemas, one boundary schema**. A unified user
experience does not require all schema details to live in one source file.

## Parsing and Precedence Stay Behind One Service

Feature modules do not locate files, parse JSONC, resolve variables, or implement
precedence rules. The config implementation does that once. It decodes unknown input
through the composed schema:

```ts
      const parsed = ConfigParse.jsonc(expanded, source)
      const data = ConfigParse.schema(ConfigV1.Info, normalizeLoadedConfig(parsed), source)
```

Source: [`packages/opencode/src/config/config.ts` lines 226-227](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/config/config.ts#L226-L227).

The loader explicitly merges the global config and then project config discovered for
the current instance:

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

Source: [`packages/opencode/src/config/config.ts` lines 398-410](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/config/config.ts#L398-L410).

Consequently, consumers receive one normalized *effective* value. They are coupled to
the meaning of relevant settings, but not to storage locations or precedence.

## The Config Boundary Is an Injected Service

The most important runtime boundary is this interface and Effect service tag:

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

Source: [`packages/opencode/src/config/config.ts` lines 124-135](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/config/config.ts#L124-L135).

That is not an exported `const config = parseFile(...)`. `Service` is a key for a
value supplied by an Effect `Layer`. The production layer closes over filesystem,
authentication, account, environment, npm, and HTTP services, then returns an
implementation of only the interface:

```ts
    return Service.of({
      get,
      getGlobal,
      getConsoleState,
      update,
      updateGlobal,
      invalidate,
      directories,
      waitForDependencies,
    })
```

Source: [`packages/opencode/src/config/config.ts` lines 662-671](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/config/config.ts#L662-L671).

The module also declares its dependency graph as data:

```ts
export const node = LayerNode.make({
  service: Service,
  layer: layer,
  deps: [FSUtil.node, Auth.node, Account.node, Env.node, Npm.node, httpClient],
})
```

Source: [`packages/opencode/src/config/config.ts` lines 675-679](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/config/config.ts#L675-L679).

`LayerNode` checks at the type level whether a layer's required services are present
in its declared dependencies:

```ts
type Missing<Required, Dependencies extends NodeList> = Exclude<Required, Output<Dependencies[number]>>
type CheckDependencies<Implementation extends Layer.Any, Dependencies extends NodeList> = [
  Missing<Layer.Services<Implementation>, Dependencies>,
] extends [never]
  ? unknown
  : { readonly "Missing dependencies": Missing<Layer.Services<Implementation>, Dependencies> }
```

Source: [`packages/core/src/effect/layer-node.ts` lines 9-14](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/core/src/effect/layer-node.ts#L9-L14).

Finally, the application root composes `Config.node` alongside the feature nodes and
builds one runtime layer. This is the composition root where concrete wiring belongs,
rather than wiring hidden in feature imports:

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
```

Source: [`packages/opencode/src/effect/app-runtime.ts` lines 58-69](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/effect/app-runtime.ts#L58-L69).

## What a Consumer Actually Imports

OpenCode's `Agent` module *does* import `Config`; it does not avoid that dependency.
What it imports is the service tag and node definition, not a loaded global value. Its
layer requests the service from context:

```ts
  Effect.gen(function* () {
    const config = yield* Config.Service
    const auth = yield* Auth.Service
    const plugin = yield* Plugin.Service
    const skill = yield* Skill.Service
    const provider = yield* Provider.Service
```

Source: [`packages/opencode/src/agent/agent.ts` lines 90-95](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/agent/agent.ts#L90-L95).

It reads config while constructing state for an instance and selects the fields it
needs:

```ts
      Effect.fn("Agent.state")(function* (ctx) {
        const cfg = yield* config.get()
        const skillDirs = yield* skill.dirs()
        const referenceDirs = Object.keys(cfg.references ?? cfg.reference ?? {}).length
```

Source: [`packages/opencode/src/agent/agent.ts` lines 99-103](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/agent/agent.ts#L99-L103).

The agent's declared graph makes the dependency visible:

```ts
export const node = LayerNode.make({
  service: Service,
  layer: layer,
  deps: [Config.node, Auth.node, Plugin.node, Skill.node, Provider.node, locationServiceMapNode],
})
```

Source: [`packages/opencode/src/agent/agent.ts` lines 447-451](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/agent/agent.ts#L447-L451).

The task tool follows the same pattern. It asks for `Config.Service`, then reads the
specific `subagent_depth` policy when executing:

```ts
    const config = yield* Config.Service
    const sessions = yield* Session.Service
```

Source: [`packages/opencode/src/tool/task.ts` lines 86-87](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/tool/task.ts#L86-L87).

```ts
      const cfg = yield* config.get()
      const runInBackground = params.background === true
```

Source: [`packages/opencode/src/tool/task.ts` lines 96-97](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/tool/task.ts#L96-L97).

```ts
      if (depth >= (cfg.subagent_depth ?? 1)) {
```

Source: [`packages/opencode/src/tool/task.ts` line 111](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/tool/task.ts#L111).

This gives OpenCode explicit dependency injection, but it is not the narrowest
possible interface. Both Agent and Task can see the entire `Info` object returned by
`get()`.

## "Global" Config Becomes Instance-Scoped State

OpenCode can serve multiple project directories. A single process-wide effective
config would be wrong because project config participates in the merge. The config
service therefore builds state through `InstanceState.make` and selects the config
for the current instance:

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

Source: [`packages/opencode/src/config/config.ts` lines 600-608](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/config/config.ts#L600-L608).

The instance context is deliberately small:

```ts
export interface InstanceContext {
  directory: string
  worktree: string
  project: Project.Info
}
```

Source: [`packages/opencode/src/project/instance-context.ts` lines 5-9](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/project/instance-context.ts#L5-L9).

`InstanceState` obtains the ambient instance reference, caches by directory, and
invalidates that directory when its instance is disposed:

```ts
export const context = Effect.gen(function* () {
  const ctx = yield* InstanceRef
  if (!ctx) return yield* Effect.die(new Error("InstanceRef not provided"))
  return ctx
})
```

Source: [`packages/opencode/src/effect/instance-state.ts` lines 14-18](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/effect/instance-state.ts#L14-L18).

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

Source: [`packages/opencode/src/effect/instance-state.ts` lines 30-39](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/effect/instance-state.ts#L30-L39).

Thus the user-level file is global in *precedence scope*, while the value observed by
a feature is an instance-specific merge. This prevents one project's config from
becoming accidental mutable state for another project.

## Replacement Is Built In

Because consumers request a service by interface, tests can supply a replacement
without creating real config files or initializing the production loader. OpenCode's
test fixture constructs a complete fake with overridable methods:

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
```

Source: [`packages/opencode/test/fixture/config.ts` lines 5-17](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/test/fixture/config.ts#L5-L17).

```ts
export function layer(overrides?: Partial<Config.Interface>) {
  return Layer.succeed(Config.Service, make(overrides))
}
```

Source: [`packages/opencode/test/fixture/config.ts` lines 19-21](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/test/fixture/config.ts#L19-L21).

That substitution seam is a concrete benefit over importing an initialized singleton.

## Coupling Assessment

OpenCode avoids several strong forms of coupling:

- Feature modules do not know config filenames or directories.
- They do not know source precedence or merge mechanics.
- They do not parse or validate config.
- They do not own config cache lifecycle.
- They do not import an eagerly initialized mutable config object.
- Production wiring and test replacement happen through layers.

But important coupling remains:

- Many modules import the central `Config` module.
- `Config.Interface.get()` returns the broad aggregate `Info`, not a feature-specific
  projection.
- Consumers directly name keys such as `subagent_depth`, `permission`, `provider`, or
  `references`.
- The top-level schema package knows every configuration domain because it is the
  public boundary's composition root.

The result is best described as **a modular implementation behind an application-wide
configuration service**, not as complete independence from a global model.

If stronger isolation were needed, a feature could depend on a narrow capability such
as a subagent-policy port or an agent-settings port. Those are illustrative names, not
upstream excerpts. The config layer would implement those ports by projecting
`ConfigV1.Info`. OpenCode has not generally taken that extra step, likely because
direct field selection is simpler and the configuration object is already a deliberate
application boundary.

## Reusable Design Recipe

The transferable design is:

```text
1. Let each domain own its schema and inferred type.
2. Compose domain schemas once at the application's external boundary.
3. Generate editor-facing JSON Schema from the runtime schema.
4. Centralize loading, validation, normalization, and precedence.
5. Expose behavior through an injected service, never an initialized object.
6. Resolve effective values in the relevant runtime scope (project, tenant, request).
7. Declare dependencies at a composition root and make them replaceable in tests.
8. Add narrow feature ports only where the broad config service causes real churn.
```

This recipe is an original synthesis, not an upstream code excerpt. Its concrete bases
are the [composed config schema](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/core/src/v1/config/config.ts#L32-L44),
the [service boundary](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/config/config.ts#L124-L135),
the [instance-scoped cache](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/src/effect/instance-state.ts#L26-L52),
and the [test replacement layer](https://github.com/anomalyco/opencode/blob/909db63265971d67d2fe4ba7f9d7b74cc33e2fdc/packages/opencode/test/fixture/config.ts#L19-L21).

The central lesson is that one user-facing file does not force one global runtime
object. A unified boundary and modular internals are compatible. Dependency injection
and instance scoping remove the most dangerous coupling, while honest use of a shared
aggregate type keeps some compile-time coupling visible rather than pretending it does
not exist.
