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

1. We have created a record tool call plugin - /home/vikram_orbio_earth/personal/dotfiles-wt/opencode/sandbox/cli-v2/fixtures/plugins/record-tool-call.ts. 
   - The idea is that we can tune it so that we can record tool calls in a file and test this file against an expectation.
2. First figure out how subagent runs work? Is it just a tool call?
   - If its just a tool call then, we just need to use the record tool call plugin
3. Then create a scenario spec that allows multi-agent runs 
   - But all it should do is simulate starting a run, getting back a tool call, then see what the agent decides.
   - We probably have to intercept tool calls
   - We probably have to create an artificial session

## Architecture Improvements

### SQLite reading

- OpenCode persists sessions via SQLite.
- We should have a simple command handler way of reading this sqlite for sessions, maybe just point a worktree and get back a table on the screen.
