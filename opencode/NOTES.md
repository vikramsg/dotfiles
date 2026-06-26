1. Permission issues
    * even after giving *.local permissions it keeps doing arbitrary permission questions
2. Add a teaching agent. That does not read files and only answers based on idiomatic usage
3. Create a plugin that auto approves any read/glob access to .local, .config... etc
    * And auto denies everything else
4. The implementer, since it creates tests first, always then creates backward compatiblity shims after

## Agent requirements

1. For each project, the reviewer has to be much stronger.
2. Maybe the structure should be
    a. What is business logic
    b. What are the layers
    c. What existing patterns and interfaces are we using
    d. What new interfaces are we creating


## Prompt

1. Do not remove pre-existing changes from the PR
2. Do not remove plan.md or ticket.md
3. Make sure to add code comments as stated in patterns and docstrings
4. Every decision you make that is not directly in the plan, record in implementation_notes.md for me to review at the end
5. Make sure all checks and tests are green.
6. Do not add tests asserting logs, code comments, docstrings, descriptions. All tests should be for actual functionality. Code comments/docstrings/logs are not functionality.

