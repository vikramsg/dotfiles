1. Make planner use the subagent instead of duplicating.
2. When using, always make the planner first come up with a plan.
    - Then look at whether the orcehstrator is giving all of it.
3. Make the reviewer, review with no context except intent. 
    - Reviewer is still getting notes like this - 
"""
Review task:
Independently review current repository changes for the overall PR intent only. Do not rely on implementation notes. Verify that:
- Production fix is in the correct layer: fallback S2 basemap AOI preparation, not `_plot_retrievals`.
- `_plot_retrievals` crop semantics are unchanged.
- ±5 day search-window logic is not refactored/moved as part of this fix.
- Carbon Mapper fallback AOI includes both plume source and asset geometry.
- Non-Carbon-Mapper fallback remains source-only.
- Empty Carbon Mapper asset geometry fails fast.
- New pytest tests are one behavior per test function and use GIVEN/WHEN/THEN comments.
- Tests are not log-only or over-mocked.
- The live repro script was run and confirms the previous failing case now works.
- No unnecessary production logic drift, fallbacks, or bugs were introduced.
"""
4. Debug
    * The workflow I have now is to prompt it to first create a temporary reproduction script, give it config, logs.
    * Then prompt it to reproduce, only then do the full loop to make sure the reproduction passes after
    * But I think I need to have this as a separate workflow, because the first loop should be pure reproduction
5. Need an OpenCode testing sandbox
    * Commands that can test a single agent/subagent with logs and output.
    * Hooks or plugins that can run an orchestrator and stop at a specific subagent
