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

## Environment variables

- `OPENCODE_SANDBOX_ROOT`: Override the sandbox root. If unset, a temporary sandbox root is created.
- `OPENCODE_SANDBOX_MODEL`: Override the model written to the generated sandbox config.
- `OPENCODE_SANDBOX_STOP_PHASE`: For `orchestrator-until` only. Defaults to `after`; `before` is also allowed.

## Output artifacts

Artifacts are written under `<sandbox-root>/output`:

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
npm --prefix opencode run build
npm --prefix opencode run test:sandbox
```

`npm --prefix opencode run build` runs the OpenCode package build. It checks the orchestration-state plugin and compiles the sandbox TypeScript CLI.

`npm --prefix opencode run test:sandbox` builds the sandbox CLI and runs the sandbox CLI tests. The tests use a fake `opencode` executable, so they do not make real model calls.

## Notes

- The CLI creates isolated XDG config, data, cache, and state homes under the sandbox root.
- It copies `auth.json` and `mcp-auth.json` into the sandbox data directory if they are present.
- The sandbox is intentionally left in place for inspection after each run.
- Database files are not deleted; cleanup is limited to known marker and status files.
- Subcommands belong to the CLI. The `justfile` is only the forwarding entrypoint.
