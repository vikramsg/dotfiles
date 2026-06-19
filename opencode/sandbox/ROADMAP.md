# OpenCode Sandbox CLI v2 Roadmap

## Direction

1. `cli-v2` has a `scenario` command with which we can run all kinds of scenarios.
   - Given a prompt, what do we get as output.
   - Given a multi-agent prompt, what is the task call?
   - Given a subagent return, what next steps does the main agent do
2. `DSPy` integration so that any agent can be optimized.
    * Eventually also multi-agent optimization
3. Both `cli-v2.ts` and `DSPy` should be packagable into a single artifact for eventual release as a separate repo.

## Next Steps

1. We have created a record tool call
2. Then create a scenario spec that allows multi-agent runs 
   - But all it should do is simulate starting a run, getting back a tool call, then see what the agent decides.
   - We probably have to intercept tool calls
   - We probably have to create an artificial session

## CLI Architecture Improvements

### High-Prio

1. Add metadata

   Write a `metadata.json` file containing sandbox paths, source files, copied sandbox files, agent name, prompt, and generation time. This makes failed real runs inspectable after the process exits.

2. Copy auth files explicitly.

   Add a helper that copies `auth.json` and `mcp-auth.json` from the user OpenCode data directory into the sandbox data directory. Keep this behavior explicit and separate from config copying.

3. Split into multiple modules once we go beyond single agent.

    Requires figuring out ideal folder structure as well


### Possible 

1. Add run artifacts to `cli-v2.ts`.

   `createSingleAgentSandboxLayout` already creates an `output` directory, but current runs do not write anything there. Add layout paths for `command.txt`, `events.jsonl`, `opencode.log`, `metadata.json`, `exit-status.txt`, and `opencode-exit-status.txt`.

2. Run OpenCode in diagnostic JSON mode.

   Current runs use `opencode run --dir <worktree> --agent <agent> <prompt>`. Prefer `opencode run --dir <worktree> --agent <agent> --format json --print-logs --log-level DEBUG <prompt>` so output can be inspected and validated.

3. Stop using inherited stdio in `runSingleAgentInSandbox`.

   Use piped stdio so stdout can be saved to `events.jsonl` and stderr can be saved to `opencode.log`. Keep terminal output to short summaries through the injected `CliIO` interface.

4. Preserve signal exit statuses.

   Map signal exits to shell-style statuses, such as `SIGINT -> 130` and `SIGTERM -> 143`, instead of collapsing them to `1`.

5. Improve config sandboxing through an explicit transform.

   Keep config copying explicit, but add an optional config transform hook so callers can override `instructions`, model, or plugins without making sandbox preparation magical.

6. Reduce command action duplication.

   The command actions repeat source-root resolution, sandbox-root resolution, spec creation, preparation, and execution. Extract small helpers only where they remove direct duplication without introducing a framework.

7. Support `OPENCODE_SANDBOX_ROOT`.

    Prefer `--dest` when provided, otherwise use `OPENCODE_SANDBOX_ROOT`, otherwise create a temporary root. Read injected `deps.env` before falling back to `process.env`.

8. Remove or use unused spec fields.

    `sourceRoot` is currently carried in `SingleAgentSandboxSpec` but is not used after construction. Either write it to metadata or remove it from the spec.

9. Figure out why the DB keeps getting migrated?

    Are we copying over the DB?
