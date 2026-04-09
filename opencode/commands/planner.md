---
description: Produce a complete actionable implementation plan in reviewer-ready PR format, with mandatory diagrams, explicit guidance, risk review, and a verification-first checklist.
agent: plan
subtask: false
---

$ARGUMENTS

# Core guidance

# Output requirements

Return markdown in exactly this structure:

```md
## Executive Summary

<A concise PR-style explanation of the change, why it exists, and the most important constraints or invariants.>

Key constraints:
- <constraint>
- <constraint>
- <constraint>

**Guidance**
`Do Not` stop until all verification and acceptance criteria is met.
Start with a test first approach with writing failing tests, making sure they fail
and then proceeding with implementation.

## Architecture and Data Flow

<Explain the end-to-end request/render/data path that matters for this change.>

```text
<MANDATORY ASCII diagram>

Requirements:
- Always include this ASCII diagram
- Show the full relevant user flow, not just one layer in isolation
- Use ASCII to represent UI where applicable
- Prefer full filenames in call stacks and flow diagrams
- Show where the new logic belongs
- Show where regressions could happen
- Include edge-case handling points if they matter
```

## Acceptance Scenarios (BDD)

### Scenario 1: <user-visible or system-critical behavior>
- Given ...
- When ...
- Then ...
- And ...

### Scenario 2: <next key behavior>
- Given ...
- When ...
- Then ...
- And ...

<Add as many scenarios as needed to fully cover the requested change and regressions.>

Guidance:
- Prefer user-visible outcomes and architecture-critical invariants
- Include regression scenarios when preserving existing behavior matters
- Cover edge cases and null/empty/fallback behavior where relevant

---

## Impact Matrix

<Add a reviewer-oriented table ordered by importance, highest-risk files first.>

| File / Domain | Change Type | Impact / Purpose | Risk |
| :--- | :--- | :--- | :--- |
| `<path>` | `<feature/refactor/test/contract/ui/etc>` | `<why this file matters>` | `<High/Medium/Low>` |

Guidance:
- Include both production and test files
- Order by reviewer importance, not alphabetically
- Call out deleted files or ownership moves explicitly
- Mention unchanged-but-regression-sensitive files when important

---

## Patterns to Follow

<The type of patterns to follow for code, for example, layer rules, how to isolate/denote private fns, how to use types etc>
<important: Do not write generic code. Make it as representative as possible>
<important: Do not write python code if we will not write python code as part of the implementation and vice versa for javascript>
1. 
```python
<this is the type of pattern I will follow if there is python code>
```

2.
```javascript
<this is the type of pattern I will follow if there was javascript code>
```

---

## Highest-Risk Review Points

These are the places where a reviewer is most likely to find subtle bugs.

### 1. <specific risk title>

Why this is risky:
- ...
- ...

What to inspect:
- `<path>`
- `<path>`

What should be true:
- ...
- ...

### 2. <specific risk title>

Why this is risky:
- ...
- ...

What to inspect:
- `<path>`
- `<path>`

What should be true:
- ...
- ...

<Add all major risk areas. Focus on correctness, ownership boundaries, contract drift, regressions, and test weakness.>

---

## Implementation Checklist

1. Read the relevant implementation and test files to confirm the current flow, ownership boundaries, edge cases, and regression-sensitive behavior.
2. Add failing tests for the highest-risk behavior first.
3. Run the targeted test command to confirm the test fails for the expected reason.
4. If the test does not fail, correct the test before implementing any production change.
5. Add failing tests for contract, schema, presenter, or type-threading changes where applicable.
6. Run the targeted test command to confirm those tests fail correctly.
7. Add failing UI, component, integration, or end-to-end tests for visible behavior and regression constraints where applicable.
8. Run the targeted test command to confirm failure.
9. Implement the backend, domain, repository, or refactor changes in the correct ownership layer.
10. Implement contract, presenter, serializer, and type propagation so new fields survive end to end.
11. Implement UI behavior while preserving existing semantics, fallbacks, visibility rules, and export behavior.
12. Remove superseded code paths, shims, or duplicate sources of truth if the new ownership model replaces them.
13. Re-run all targeted tests and resolve failures.
14. Run broader verification commands for formatting, linting, typechecking, and tests.
15. If browser-based smoke testing is available and the change is user-facing, run a smoke check for the changed flow.
16. If export, download, or visibility behavior is relevant, verify that flow explicitly during smoke testing.
17. Re-check the acceptance scenarios against the implemented behavior.
18. Prepare a PR description that clearly states scope, constraints, and regression protections.
```

