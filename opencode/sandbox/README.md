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

`cli-v2.ts` is the in-progress rewrite of the sandbox CLI. It supports `hello`, `hello-world`, explicit `single-agent` runs, and scenario/evaluation runs for candidate agent checks. Run it through the package script:

```sh
npm --prefix opencode run sandbox:v2 -- <command> <args...>
```

Examples:

```sh
npm --prefix opencode run sandbox:v2 -- hello
npm --prefix opencode run sandbox:v2 -- hello-world
npm --prefix opencode run sandbox:v2 -- single-agent --agent custom-agent --agent-file ./sandbox/fixtures/agents/hello-world.md --prompt "Run this agent."
npm --prefix opencode run sandbox:v2 -- scenario --scenario sandbox/scenarios/passing-positive/scenario.json --timeout-ms 60000
npm --prefix opencode run sandbox:v2 -- evaluate --scenario sandbox/scenarios/reviewer-overreach/scenario.json --agent-candidate orchestrator=/tmp/candidate.md --json
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
- Provides fixture commands for `hello` and `hello-world`, plus explicit `single-agent` runs.
- `scenario` prepares the sandbox, copies fixture worktree files, installs a generated trace/expectation plugin when `scriptedSubagents` are configured, then runs the primary agent through `opencode run`.
- `evaluate` runs the same captured primary-agent path and scores the required `transcript.jsonl`; static `scenario.transcript` data is not the default scoring path.
- `--agent-candidate agent=/path/to/file.md` replaces a scenario agent before running, so scores are derived from the candidate behavior observed in the sandbox trace.
- `--timeout-ms <number>` terminates long-running captured scenario/evaluation runs and records timeout status in artifacts.
- `evaluate --json` writes the parseable evaluation JSON to stdout before exiting non-zero when the evaluation fails.

Current limitations:

- Does not yet support orchestrator commands such as `orchestrator-until` or `orchestrator-final-check`.
- Scenario/evaluation deterministic scoring depends on the sandbox trace/expectation plugin recording task, read-only tool, and final-response events. `scriptedSubagents` are expected task-output sequences used for validation; unexpected, exhausted, or mismatched task calls fail evaluation instead of being treated as successful fallback behavior.
- CLI v2 does not yet prove true task short-circuiting/stubbing and is not a DSPy optimizer.
- Does not yet generate stop plugins for CLI v2 orchestrator convenience commands.
- Does not yet generate a harness for subagent-mode agents.

## CLI v2 Scenario Artifacts

Captured `scenario` and `evaluate` runs write artifacts under `<sandbox-root>/output`:

- `result.json`: structured command, stdout/stderr, exit status, timeout flag, and signal.
- `stdout.txt`: captured `opencode run` stdout.
- `stderr.txt`: captured `opencode run` stderr.
- `transcript.jsonl`: trace events recorded by the generated sandbox trace/expectation plugin or by an instrumented test `opencode`.
- `final-response.md`: captured stdout used as the fallback final response.
- `status.json`: exit status, timeout flag, and signal.
- `metadata.json`: command and worktree metadata.
- `evaluation.json`: top-level `passed` result, raw OpenCode `status`, assertion results, trace errors, and score inputs written by `evaluate`.

Malformed, missing, or empty required traces are reported as failed `evaluate` results with non-empty `trace_errors` instead of falling back to fixture transcripts; `evaluate --json` still writes parseable evaluation JSON to stdout and `output/evaluation.json`. Completed evaluations exit `0` only when `evaluation.json.passed` is `true`; failed assertions, trace expectation errors, timeouts, and non-zero OpenCode statuses return `1` while preserving raw run details in the artifacts.

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
npm --prefix opencode run test:sandbox:v2
```

`npm --prefix opencode run build` runs the OpenCode package build. It checks the orchestration-state plugin and compiles the sandbox TypeScript CLI.

`npm --prefix opencode run test:sandbox:v2` builds the sandbox CLI and runs the CLI v2 sandbox tests. The tests use a fake `opencode` executable, so they do not make real model calls.
CLI v2 tests assert the clean user-facing stderr contract and intentionally do not mock or assert logger internals; real `pino` diagnostics may appear on terminal stderr during test runs.

## Notes

- The CLI creates isolated XDG config, data, cache, and state homes under the sandbox root.
- The sandbox is intentionally left in place for inspection after each run.
- Database files are not deleted; cleanup is limited to known marker and status files.
- Subcommands belong to the CLI. The `justfile` is only the forwarding entrypoint.
