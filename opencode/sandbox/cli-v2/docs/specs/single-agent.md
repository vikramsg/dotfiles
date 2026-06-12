# Single Agent

`single-agent` runs one requested OpenCode agent in an isolated sandbox and records the process artifacts.

```text
user
  |
  v
single-agent options
  |
  v
validate files and prompt source
  |
  v
prepare isolated XDG homes
  |
  v
opencode run --dir <worktree> --agent <agent> <prompt>
  |
  v
output artifacts
```

## Contracts

- The command runs exactly one named agent.
- The command accepts exactly one prompt source: `--prompt` or `--prompt-file`.
- The command copies the source config, safe local plugins, and requested agent into the sandbox config home.
- The command returns the OpenCode process status for normal runs.

## Flow

1. Parse command options.
2. Read the prompt text or prompt file.
3. Validate the agent name and local plugin paths.
4. Create sandbox XDG directories under the destination root.
5. Copy the source config, safe local plugins, and one agent file.
6. Run `opencode run` against the sandbox worktree.
7. Forward OpenCode output while writing artifacts.

## Inputs

- `--orig <path>` source OpenCode config root.
- `--dest <path>` sandbox destination directory.
- `--config <path>` source config file, relative to `--orig` unless absolute.
- `--agent <name>` OpenCode agent name.
- `--agent-file <path>` source agent file, relative to `--orig` unless absolute.
- `--prompt <text>` prompt text.
- `--prompt-file <path>` prompt file.
- `--timeout-ms <number>` optional CLI timeout.

## Outputs

Artifacts are written under `<sandbox-root>/output`:

- `command.txt`
- `metadata.json`
- `stdout.txt`
- `stderr.txt`
- `opencode-exit-status.txt`
- `exit-status.txt`

## Lifecycle

- Setup errors stop before OpenCode starts.
- A missing OpenCode executable returns `127`.
- A CLI timeout returns `124`.
- OpenCode stdout and stderr are forwarded and captured.

## Errors

- Missing required options return a concise usage error.
- Unsafe agent names are rejected.
- Absolute or escaping local plugin paths are rejected.
- Malformed config JSON is rejected.

## Non-Goals

- No grading rules.
- No golden-output comparison.
- No legacy sandbox refactor.
- No multi-agent orchestration.

## Implementation Notes

- CLI v2 imports only local CLI v2 modules and package or Node dependencies.
- CLI v2 runs directly from `sandbox/cli-v2/index.ts`, so local imports use `.ts` specifiers and root resolution starts from the source directory.
