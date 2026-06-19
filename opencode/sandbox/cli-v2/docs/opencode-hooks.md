# OpenCode Plugin Hooks

## Plugin Loading Model

A plugin module exports one or more plugin functions. OpenCode imports loaded
plugin modules, calls exported plugin functions during initialization, and uses
the returned object to register hooks.

Example:

```ts
export const MyPlugin = async (ctx, options) => {
  return {
    "tool.execute.after": async (input, output) => {
      // Hook implementation.
    },
  };
};
```

The parameter name does not matter. OpenCode does not call a plugin because an
argument is named `context`, `ctx`, or anything else. It calls exported plugin
functions from loaded plugin modules. The returned object tells OpenCode which
lifecycle callbacks to invoke.

Local plugin loading from the public docs:

- Project plugins: `.opencode/plugins/`
- Global plugins: `~/.config/opencode/plugins/`
- Configured npm/local plugins: `plugin` entries in `opencode.json`

## Plugin Initialization Context

Current upstream plugin context shape:

```ts
type PluginInput = {
  client: ReturnType<typeof createOpencodeClient>;
  project: Project;
  directory: string;
  worktree: string;
  experimental_workspace: {
    register(type: string, adapter: WorkspaceAdapter): void;
  };
  serverUrl: URL;
  $: BunShell;
};
```

Context fields:

- `client`: OpenCode SDK client for interacting with the running OpenCode server.
- `project`: Current project metadata.
- `directory`: Current working directory for the OpenCode session.
- `worktree`: Git worktree path.
- `experimental_workspace`: Experimental workspace adapter registration API.
- `serverUrl`: OpenCode server URL.
- `$`: Bun shell API for running local commands.

Plugin options are passed as the second argument when a plugin is configured as
a tuple in `opencode.json`:

```json
{
  "plugin": [["my-plugin", { "key": "value" }]]
}
```

## Hook Object Keys

These are keys that may be returned from a plugin function:

- `dispose`
- `event`
- `config`
- `tool`
- `auth`
- `provider`
- `chat.message`
- `chat.params`
- `chat.headers`
- `permission.ask`
- `command.execute.before`
- `tool.execute.before`
- `shell.env`
- `tool.execute.after`
- `experimental.chat.messages.transform`
- `experimental.chat.system.transform`
- `experimental.provider.small_model`
- `experimental.session.compacting`
- `experimental.compaction.autocontinue`
- `experimental.text.complete`
- `tool.definition`

Hook object keys and event bus event types are different concepts. Some names
overlap, but `event` receives bus events while hook object keys register direct
lifecycle callbacks.

## Event Hook Event Types

The generic `event` hook receives raw OpenCode bus events:

```ts
event?: (input: { event: Event }) => Promise<void>;
```

Public docs list these event types:

- `command.executed`
- `file.edited`
- `file.watcher.updated`
- `installation.updated`
- `lsp.client.diagnostics`
- `lsp.updated`
- `message.part.removed`
- `message.part.updated`
- `message.removed`
- `message.updated`
- `permission.asked`
- `permission.replied`
- `server.connected`
- `session.created`
- `session.compacted`
- `session.deleted`
- `session.diff`
- `session.error`
- `session.idle`
- `session.status`
- `session.updated`
- `todo.updated`
- `shell.env`
- `tool.execute.after`
- `tool.execute.before`
- `tui.prompt.append`
- `tui.command.execute`
- `tui.toast.show`

Use `event` for observation across the event bus. Use direct hook keys when a
plugin needs a typed lifecycle callback with mutable output.

## Hook Reference

### `dispose`

Called when the plugin is disposed or shut down.

Signature:

```ts
dispose?: () => Promise<void>;
```

### `event`

Receives raw OpenCode bus events.

Signature:

```ts
event?: (input: { event: Event }) => Promise<void>;
```

### `config`

Called with the merged config. Mutate the config object in place if needed.

Signature:

```ts
config?: (input: Config) => Promise<void>;
```

### `tool`

Registers custom tools.

Shape:

```ts
tool?: {
  [key: string]: ToolDefinition;
};
```

### `auth`

Registers provider authentication methods.

Shape:

```ts
auth?: AuthHook;
```

### `provider`

Registers or extends provider model behavior.

Shape:

```ts
provider?: ProviderHook;
```

### `chat.message`

Called when a new message is received.

Input:

```ts
{
  sessionID: string;
  agent?: string;
  model?: { providerID: string; modelID: string };
  messageID?: string;
  variant?: string;
}
```

Output:

```ts
{
  message: UserMessage;
  parts: Part[];
}
```

### `chat.params`

Mutates parameters sent to the language model.

Input:

```ts
{
  sessionID: string;
  agent: string;
  model: Model;
  provider: ProviderContext;
  message: UserMessage;
}
```

Output:

```ts
{
  temperature: number;
  topP: number;
  topK: number;
  maxOutputTokens: number | undefined;
  options: Record<string, any>;
}
```

### `chat.headers`

Mutates headers for chat/model requests.

Input:

```ts
{
  sessionID: string;
  agent: string;
  model: Model;
  provider: ProviderContext;
  message: UserMessage;
}
```

Output:

```ts
{
  headers: Record<string, string>;
}
```

### `permission.ask`

Called when OpenCode asks for permission.

Input:

```ts
Permission
```

Output:

```ts
{
  status: "ask" | "deny" | "allow";
}
```

### `command.execute.before`

Called before a command executes.

Input:

```ts
{
  command: string;
  sessionID: string;
  arguments: string;
}
```

Output:

```ts
{
  parts: Part[];
}
```

Use this to inspect slash/custom commands and inject parts into the command
execution flow. For example, `plugins2/orchestration-state.js` uses this hook
to create or resume persisted orchestration state before the `orchestrate`
command runs.

### `tool.execute.before`

Called before a tool executes.

Input:

```ts
{
  tool: string;
  sessionID: string;
  callID: string;
}
```

Output:

```ts
{
  args: any;
}
```

Mutate `output.args`, not `input`, to rewrite tool arguments. Throw an error to
block execution.

### `shell.env`

Called when building shell environment variables.

Input:

```ts
{
  cwd: string;
  sessionID?: string;
  callID?: string;
}
```

Output:

```ts
{
  env: Record<string, string>;
}
```

### `tool.execute.after`

Called after a tool executes.

Input:

```ts
{
  tool: string;
  sessionID: string;
  callID: string;
  args: any;
}
```

Output:

```ts
{
  title: string;
  output: string;
  metadata: any;
}
```

Use this to observe or persist tool results. For example,
`plugins2/orchestration-state.js` uses this hook to persist `task` tool output
from planner, implementer, and reviewer subagents.

### `experimental.chat.messages.transform`

Transforms the message list before a model call.

Input:

```ts
{}
```

Output:

```ts
{
  messages: {
    info: Message;
    parts: Part[];
  }[];
}
```

### `experimental.chat.system.transform`

Transforms system prompt/context.

Input:

```ts
{
  sessionID?: string;
  model: Model;
}
```

Output:

```ts
{
  system: string[];
}
```

### `experimental.provider.small_model`

Allows selecting a small model for a provider.

Input:

```ts
{
  provider: ProviderV2;
}
```

Output:

```ts
{
  model?: ModelV2;
}
```

### `experimental.session.compacting`

Runs before session compaction starts.

Input:

```ts
{
  sessionID: string;
}
```

Output:

```ts
{
  context: string[];
  prompt?: string;
}
```

Append to `output.context` to add compaction context. Set `output.prompt` to
replace the default compaction prompt entirely.

### `experimental.compaction.autocontinue`

Runs after compaction succeeds and before OpenCode adds a synthetic user
continue message.

Input:

```ts
{
  sessionID: string;
  agent: string;
  model: Model;
  provider: ProviderContext;
  message: UserMessage;
  overflow: boolean;
}
```

Output:

```ts
{
  enabled: boolean;
}
```

Set `output.enabled = false` to skip the synthetic continue turn.

### `experimental.text.complete`

Runs after text completion.

Input:

```ts
{
  sessionID: string;
  messageID: string;
  partID: string;
}
```

Output:

```ts
{
  text: string;
}
```

### `tool.definition`

Mutates tool definitions sent to the language model.

Input:

```ts
{
  toolID: string;
}
```

Output:

```ts
{
  description: string;
  parameters: any;
}
```

## Source Of Truth

The hook surface can vary by OpenCode and `@opencode-ai/plugin` package version.
This document is based on:

- OpenCode plugin docs: `https://opencode.ai/docs/plugins/`
- Published package types: `@opencode-ai/plugin@1.4.2/dist/index.d.ts`
- Current upstream source: `packages/plugin/src/index.ts`

When behavior matters, prefer the installed package type definitions for the
OpenCode version being used.

