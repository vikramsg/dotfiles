# Scenario

`scenario` runs a saved sandbox recipe. The recipe describes repeatable inputs for one OpenCode run.

```text
user
  |
  v
scenario <scenario-dir>
  |
  v
read scenario.json and prompt.md
  |
  v
copy fixture worktree
  |
  v
opencode run --dir <worktree> --agent <agent> <prompt>
  |
  v
output artifacts
```

## Contracts

- A scenario is a repeatable run recipe.
- A scenario runs one primary agent.
- `promptFile` and `fixtureDir` are resolved relative to the scenario folder.
- `agentFile` and optional `config` are resolved relative to the CLI v2 folder unless absolute.
- The command uses the same artifact shape as `single-agent`.

## Flow

1. Parse the scenario directory.
2. Read `scenario.json`.
3. Resolve source config, agent file, prompt file, and fixture worktree.
4. Prepare the single-agent sandbox.
5. Copy fixture worktree contents into the sandbox worktree.
6. Run OpenCode and write artifacts.

## Inputs

`scenario.json` shape:

```json
{
  "name": "hello-world",
  "agent": "hello-world",
  "agentFile": "fixtures/agents/hello-world.md",
  "promptFile": "prompt.md",
  "fixtureDir": "worktree"
}
```

Optional fields and options:

- `config` overrides the default `../../opencode.json` path from the CLI v2 folder.
- `--dest <path>` sets the sandbox destination directory.
- `--timeout-ms <number>` sets a CLI timeout.

## Outputs

Artifacts are written under `<sandbox-root>/output`:

- `command.txt`
- `metadata.json`
- `stdout.txt`
- `stderr.txt`
- `opencode-exit-status.txt`
- `exit-status.txt`

## Lifecycle

- Scenario parsing and file resolution happen before OpenCode starts.
- Fixture worktree contents are copied after sandbox preparation.
- OpenCode stdout and stderr are forwarded and captured.
- The final status mirrors OpenCode unless the CLI reports setup, missing executable, or timeout status.

## Errors

- Missing `scenario.json` returns a concise setup error.
- Malformed scenario JSON returns a concise setup error.
- Missing prompt, fixture, config, or agent files return setup errors.
- Invalid agent names and unsafe local plugin paths are rejected.

## Non-Goals

- No grading rules.
- No golden-output comparison.
- No historical run database.
- No legacy sandbox refactor.

## Implementation Notes

- The checked-in `hello-world` scenario is the initial recipe.
- The command delegates to the single-agent preparation and run path after loading the recipe.
- CLI v2 runs directly from `sandbox/cli-v2/index.ts`; scenario-relative files are resolved from the scenario directory and CLI v2 source directory, not from a build output directory.
