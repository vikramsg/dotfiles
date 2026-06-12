# OpenCode Sandbox

## What it is

The OpenCode sandbox is a TypeScript CLI for running the real `opencode` command in isolated sandbox flows from this dotfiles repo. It is exposed through the repo-root forwarding entrypoint:

```sh
just opencode-sandbox <subcommand> <args...>
```

## Why it exists

Use it to debug or test the orchestrator and agents without touching normal OpenCode config, data, cache, or state. Each run creates isolated XDG homes under the sandbox root and leaves logs, events, markers, and status files behind for inspection.

## Subcommands

### `orchestrator-until <subagent> <prompt...>`

Runs the orchestrator with the prompt and stops when the requested subagent is observed. By default it stops after the target subagent runs.

### `orchestrator-final-check <prompt...>`

Runs the full orchestrator flow and validates the final PR check behavior. The sandbox observes reviewer approval, requires a later `read`, `glob`, or `grep` tool call by the orchestrator, and checks the final output for `Orchestrator Merge-Readiness Judgment`.

### `single-agent <agent> <prompt...>`

Runs one agent directly with the prompt. For subagent-mode agents, the CLI generates a sandbox-only primary harness agent that calls the requested real subagent.

## Examples

```sh
just opencode-sandbox orchestrator-until planner "Plan this change"
OPENCODE_SANDBOX_STOP_PHASE=before just opencode-sandbox orchestrator-until implementer "Prompt"
just opencode-sandbox orchestrator-final-check "Make a harmless text-file change and complete review"
just opencode-sandbox single-agent reviewer "Review this change"
```

## CLI v2

`cli-v2/` is the self-contained rewrite of the sandbox CLI. It currently supports only `hello`, `hello-world`, explicit `single-agent` runs, and saved `scenario` recipes. The package script runs `sandbox/cli-v2/index.ts` directly with Node; CLI v2 uses `check:sandbox:v2` for TypeScript diagnostics and does not build a CLI v2 `dist/` artifact.

Run it through the package script:

```sh
npm --prefix opencode run sandbox:v2 -- <command> <args...>
```

Examples:

```sh
npm --prefix opencode run sandbox:v2 -- hello
npm --prefix opencode run sandbox:v2 -- hello-world
npm --prefix opencode run sandbox:v2 -- single-agent --agent custom-agent --agent-file ./sandbox/cli-v2/fixtures/agents/hello-world.md --prompt "Run this agent."
npm --prefix opencode run sandbox:v2 -- scenario ./sandbox/cli-v2/scenarios/hello-world
```

Current capabilities:

- Creates isolated XDG config, data, cache, and state homes under the sandbox root.
- Emits pretty `pino` diagnostic logs to the terminal stderr while keeping captured user-facing validation stderr clean.
- Copies the OpenCode config as-is into the sandbox config directory; plugin entries are not rewritten.
- Copies configured relative local plugin files only when their normalized sandbox destination remains under `config/opencode/plugins`.
- Rejects absolute local plugin paths because the config is copied as-is and cannot safely point at a sandbox copy.
- Leaves package plugin entries for OpenCode to resolve; missing configured local plugin files fail sandbox preparation.
- Copies one selected agent file into the sandbox agent directory under the requested agent name.
- Runs `opencode run --agent <agent>` inside the sandbox worktree.
- Writes `command.txt`, `metadata.json`, `stdout.txt`, `stderr.txt`, `opencode-exit-status.txt`, and `exit-status.txt` under `<sandbox-root>/output`.
- Provides fixture commands for `hello` and `hello-world`, explicit `single-agent` runs, and saved `scenario` recipes.

Current limitations:

- Does not yet support orchestrator commands such as `orchestrator-until` or `orchestrator-final-check`.
- Does not yet write legacy-only output artifacts such as `events.jsonl`, `opencode.log`, or marker files.
- Does not yet generate observer or stop plugins.
- Does not yet generate a harness for subagent-mode agents.

## Environment variables

- `OPENCODE_SANDBOX_LOG_LEVEL`: Override CLI v2 diagnostic logging level. Defaults to `info`; use `debug` for verbose sandbox diagnostics.

## Legacy CLI Output Artifacts

The original `sandbox-cli.ts` writes artifacts under `<sandbox-root>/output`:

- `command.txt`: Reproducible command with sandbox environment variables.
- `metadata.json`: Sandbox paths and run metadata.
- `opencode.log`: OpenCode stderr and debug logs.
- `events.jsonl`: Raw OpenCode JSON event stream.
- `stop-marker.json`: Marker written by `orchestrator-until` when the target subagent is observed.
- `final-check-marker.json`: Marker written by `orchestrator-final-check` with reviewer approval and post-approval read-only tool observations.
- `single-agent-marker.json`: Marker written for `single-agent` subagent-mode runs.
- `opencode-exit-status.txt`: Raw `opencode` process exit status.
- `exit-status.txt`: Sandbox CLI validation exit status.

## Verification

Run these from the repo root after changing sandbox code:

```sh
npm --prefix opencode run build:sandbox
npm --prefix opencode run build
npm --prefix opencode run check:sandbox:v2
npm --prefix opencode run test:sandbox:v2
```

`npm --prefix opencode run build` runs the OpenCode package build. It checks the orchestration-state plugin, compiles the legacy sandbox TypeScript CLI, and typechecks CLI v2 without emitting CLI v2 build output.

`npm --prefix opencode run test:sandbox:v2` runs the CLI v2 sandbox tests without a CLI v2 build step. The tests use a fake `opencode` executable, so they do not make real model calls.
CLI v2 tests assert the clean user-facing stderr contract and intentionally do not mock or assert logger internals; real `pino` diagnostics may appear on terminal stderr during test runs.

## Notes

- The CLI creates isolated XDG config, data, cache, and state homes under the sandbox root.
- The sandbox is intentionally left in place for inspection after each run.
- Database files are not deleted; cleanup is limited to known marker and status files.
- Subcommands belong to the CLI. The `justfile` is only the forwarding entrypoint.
