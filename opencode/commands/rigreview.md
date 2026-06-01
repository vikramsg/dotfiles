---
description: Generate review.md with a GitHub-style PR diff and per-hunk review comments.
agent: rigorchestrator
subtask: false
---
$ARGUMENTS

Run the same rigor-planner -> implementer -> rigor-reviewer loop, but the task is only to create or update `review.md`.

Do not create or modify any source files, tests, agents, or commands. The only intended file output is `review.md`.

For this command, merge readiness means `review.md` is thorough, complete, and accurate. It does not mean the underlying PR code has been fixed.

## Implementer Requirements

The implementer must create `review.md`, not an implementation summary.

`review.md` must look like a GitHub PR review:

1. Include the PR-style diff for every changed file and every meaningful hunk.
2. Use separate fenced `diff` blocks for hunks.
3. Immediately after each hunk, include a `Review comments` section.
4. If a hunk has no issues, write `No comments`.
5. If a hunk has issues, comments must be specific, actionable, and anchored to the hunk context.
6. Do not include a narrative summary in `review.md`.
7. Do not recommend direct source-code edits outside `review.md`.

## Reviewer Requirements

The rigor-reviewer must review the overall PR and the completeness of `review.md`.

The reviewer must only recommend specific changes to `review.md`.

If the underlying PR has code issues, the required fix is to add or improve the relevant hunk comment in `review.md`, not to edit the source code.

Fail the review if `review.md`:

1. Omits changed files or meaningful hunks.
2. Has vague or non-actionable comments.
3. Misses important correctness, design, testing, or maintainability concerns.
4. Lacks a `Review comments` section for each hunk.
5. Includes a summary instead of a PR-style diff review.
6. Suggests modifying files other than `review.md`.

Approve only when `review.md` is a thorough and complete GitHub-style PR review artifact.

## Final Output

When complete, the final chat response must be exactly:

`review.md`
