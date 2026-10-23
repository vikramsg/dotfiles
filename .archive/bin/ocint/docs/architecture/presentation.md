# Presentation architecture

- Services and repositories return typed data and contain no presentation logic or presentation backend imports.
- `ocint.presentation` is the public facade for shared presentation components, exact machine serializers, and terminal output construction.
- Code outside `ocint.presentation` imports its APIs only from `ocint.presentation`; private modules such as `ocint.presentation._components` are implementation details.
- `presentation/__init__.py` documents the package, imports every supported public symbol, and declares those symbols in `__all__`.
- Feature `render.py` modules own domain-specific human composition: field selection, labels, ordering, and sections.
- Feature CLIs choose human or machine output, but do not call Click echo functions or Rich directly.
- Human output uses `CliOutput.display()` with renderables composed by feature renderers and shared presentation components.
- Machine JSON, JSONL, CSV, and raw output is exact and unstyled. It always uses `CliOutput.write()`, never `display()`.
- Rich and Click output backend imports stay inside `ocint.presentation`; the shared `CliOutput` protocol remains backend-neutral.
- Tests assert typed service/repository boundaries, facade-only imports, feature composition semantics, CLI routing, and exact machine output separately. Human tests do not depend on ANSI sequences or decorative borders.
