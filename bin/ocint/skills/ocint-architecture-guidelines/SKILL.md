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
