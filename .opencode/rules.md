# Review

Prefer getting your changes reviewed after implementing and verifying your changes.
Launch the `reviewer` subagent ([agents/reviewer.md](agents/reviewer.md)) in the background with two things:

- The scope: a branch range, or for a `gh stack` the PRs and whether it reviews each PR, the whole stack, or both.
- The verifications already run, as commands with results, so it does not run them again.

The reviewer judges the code, so the prompt carries no reasons for the design, no findings from earlier reviews and no claims that the behaviour is correct.
    - DO NOT provide plan or implementation note files to the reviewer.

Fix or decline each finding. Decline over-defensive and over-engineered findings. Report every declined finding to the user with a one-line reason; a later review gets no list of them.
