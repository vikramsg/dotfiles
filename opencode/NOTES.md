1. Orchestrator issues
    - The orchestrator keeps not sending full context.
2. Make planner use the subagent instead of duplicating.
3. When using, always make the planner first come up with a plan.
    - Then look at whether the orcehstrator is giving all of it.
4. Make the reviewer, review with no context except intent. 
5. Debug
    * The workflow I have now is to prompt it to first create a temporary reproduction script, give it config, logs.
    * Then prompt it to reproduce, only then do the full loop to make sure the reproduction passes after
    * But I think I need to have this as a separate workflow, because the first loop should be pure reproduction
6. Need an OpenCode testing sandbox
    * Commands that can test a single agent/subagent with logs and output.
    * Hooks or plugins that can run an orchestrator and stop at a specific subagent
7. Once the testing sandbox is ready, then make sure you can test out each subagent with the sandbox. 
    * Maybe even run it on a specific repo and branch?
8. RULES.md
    * Even if we have opencode config in repo, we can still uses untracked rules to customize
9. Permission issues
    * even after giving *.local permissions it keeps doing arbitrary permission questions
