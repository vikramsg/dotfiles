# CLI v2 Commands

## `hello`

Prints `hello world` and exits `0`. It does not start OpenCode.

```sh
npm run sandbox:v2 -- hello
# equivalent direct source entrypoint:
node sandbox/cli-v2/index.ts hello
```

## `hello-world`

Runs the self-contained fixture agent with the default package config.

```sh
npm run sandbox:v2 -- hello-world
```

Useful options:

- `--orig <path>` config root containing `opencode.json`.
- `--dest <path>` sandbox destination.
- `--timeout-ms <number>` runtime limit.

## `single-agent`

Runs one explicit agent.

```sh
npm run sandbox:v2 -- single-agent --agent custom-agent --agent-file agents/custom-agent.md --prompt "Hello"
```

Useful options:

- `--orig <path>` config root.
- `--dest <path>` sandbox destination.
- `--config <path>` config file.
- `--agent <name>` agent name.
- `--agent-file <path>` agent source file.
- `--prompt <text>` prompt text.
- `--prompt-file <path>` prompt file.
- `--timeout-ms <number>` runtime limit.

## `scenario`

Runs a saved recipe.

```sh
npm run sandbox:v2 -- scenario sandbox/cli-v2/scenarios/hello-world
```

Useful options:

- `--dest <path>` sandbox destination.
- `--timeout-ms <number>` runtime limit.

## Development commands

CLI v2 runs directly from TypeScript source and has no build output. Use the check command for TypeScript diagnostics:

```sh
npm run check:sandbox:v2
npm run test:sandbox:v2
```
