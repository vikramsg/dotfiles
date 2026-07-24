---
name: ocint-architecture-guidelines
description: Use when adding, moving, or reviewing ocint modules, shared models, configuration, repositories, CLI commands, rendering, or package imports.
---

# ocint Architecture Guidelines

- Place code and types in the closest package that owns their responsibility.
- Keep types local until they form a stable contract across sibling modules.
- Keep `models.py` focused on its package's core vocabulary, not every imported
  type.
- Use narrow protocols for shared contracts; keep concrete validated models at
  their construction boundary.
- Construct typed values at external boundaries and pass validated, immutable
  values inward.
- Keep workflow, business rules, persistence, configuration, infrastructure,
  and presentation in their respective owners.
- Point dependencies toward contracts rather than concrete adapters.
- Use `references/module-boundaries.md` for detailed placement criteria,
  examples, and anti-patterns when useful.

## Daemon Boundaries

```text
config -> feature config
CLI -> feature facade -> runtime
runtime -> shared contracts <- consumers
```

- `daemon/cli.py` constructs and injects runtime dependencies.
- Feature configuration stays with the feature.
- Runtime features never receive or import `DaemonConfig`.
- Feature facades must not eagerly import runtime modules.
- Put a model in `daemon/models.py` only when sibling features share its meaning.
- Providers do not import task modules; provider-neutral tasks do not import a
  concrete provider.
- Enforce import boundaries with Tach, not AST tests.

Do:

```python
async with open_github_service(config.github, policies, token, path) as github:
    create_daemon_app(context, github)
```

Do not:

```python
class GitHubService:
    def __init__(self, config: DaemonConfig): ...
```

- See `references/github.md` for a concrete daemon GitHub example.
