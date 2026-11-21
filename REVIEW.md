# Review focus

Check these first when reviewing a change, your own or someone else's.

- Simplicity: could it reuse or refactor existing code instead of adding more, and is every added abstraction needed now?
- Layering: outer layers call inner ones; IO and settings only at entry points. Tools, their config and their services sit where [AGENTS.md](AGENTS.md) says (`bin/<tool>/`, `<tool>/`, `lch/config.toml`, the root `justfile`).
- Patterns: does it follow the surrounding code and the repo's other tools, or invent a new pattern?
- State: can a type hold a combination that never happens, does each piece of state have one owner, and can a late or stale result overwrite newer state?
- Boundaries: is outside input (files, command output, API responses, CLI arguments) parsed where it enters, into types that state their meaning?
- Resources: is every file, process, connection and stream released after success, failure and cancellation, by the code that opened it? Is every added limit, timeout, cache, retry or wrapper backed by a stated requirement?
- Tests: do they check behaviour, not that recently changed text is present? See [AGENTS.md](AGENTS.md).
- Writing: can a reader who has only the comment, doc or PR description and its links follow it?
- Principles: use [stick-to-your-principles](skills/principles/references/stick-to-your-principles.md) to check whether this change follows the applicable mapped principles.
