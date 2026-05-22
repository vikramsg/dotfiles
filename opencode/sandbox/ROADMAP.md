# OpenCode Sandbox CLI v2 Roadmap

## Direction

`cli-v2.ts` should stay small, composable, and testable. The rewrite should not copy all of `sandbox-cli.ts` at once. The best path is to harden the current single-agent sandbox abstraction until it is reliable, inspectable, and easy to extend.

## Highest-Value Improvements

1. Add run artifacts to `cli-v2.ts`.

   `createSingleAgentSandboxLayout` already creates an `output` directory, but current runs do not write anything there. Add layout paths for `command.txt`, `events.jsonl`, `opencode.log`, `metadata.json`, `exit-status.txt`, and `opencode-exit-status.txt`.

2. Run OpenCode in diagnostic JSON mode.

   Current runs use `opencode run --dir <worktree> --agent <agent> <prompt>`. Prefer `opencode run --dir <worktree> --agent <agent> --format json --print-logs --log-level DEBUG <prompt>` so output can be inspected and validated.

3. Validate `agentName` before writing `${agentName}.md`.

   Reject path separators, `..`, empty names, and other unsafe values before deriving sandbox file paths. A conservative pattern such as `/^[a-zA-Z0-9][a-zA-Z0-9._-]*$/` is enough for the current use case.

4. Stop using inherited stdio in `runSingleAgentInSandbox`.

   Use piped stdio so stdout can be saved to `events.jsonl` and stderr can be saved to `opencode.log`. Keep terminal output to short summaries through the injected `CliIO` interface.

5. Preserve signal exit statuses.

   Map signal exits to shell-style statuses, such as `SIGINT -> 130` and `SIGTERM -> 143`, instead of collapsing them to `1`.

6. Add metadata.

   Write a `metadata.json` file containing sandbox paths, source files, copied sandbox files, agent name, prompt, and generation time. This makes failed real runs inspectable after the process exits.

7. Improve config sandboxing through an explicit transform.

   Keep config copying explicit, but add an optional config transform hook so callers can override `instructions`, model, or plugins without making sandbox preparation magical.

8. Copy auth files explicitly.

   Add a helper that copies `auth.json` and `mcp-auth.json` from the user OpenCode data directory into the sandbox data directory. Keep this behavior explicit and separate from config copying.

9. Reduce command action duplication.

   The command actions repeat source-root resolution, sandbox-root resolution, spec creation, preparation, and execution. Extract small helpers only where they remove direct duplication without introducing a framework.

10. Support `OPENCODE_SANDBOX_ROOT`.

    Prefer `--dest` when provided, otherwise use `OPENCODE_SANDBOX_ROOT`, otherwise create a temporary root. Read injected `deps.env` before falling back to `process.env`.

11. Fix small CLI UX issues.

    Add the missing newline after `No command provided.`. Consider returning usage status `64` for usage errors later, but that is lower priority.

12. Remove or use unused spec fields.

    `sourceRoot` is currently carried in `SingleAgentSandboxSpec` but is not used after construction. Either write it to metadata or remove it from the spec.
