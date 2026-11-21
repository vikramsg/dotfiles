# Creating and managing principles

Run `principles list-principles` from the project root (or `--project PATH` in a monorepo) and follow its `next_action`.

## Survey

- Nothing mapped yet: run `principles list-candidate-files` and show the user a table of candidate principles before creating any maps.
- Existing maps: use `principles list-candidate-files --commits-after REV` to spot principles in recent changes.
- **OpenCode discovery:** `list-candidate-files` finds `AGENTS.md`, `CLAUDE.md`, `.claude/*`, `.agents/skills/`, and `.codex/*` automatically. Preview extra paths (e.g., `.opencode/**`, `REVIEW.md`, `.github/workflows/*`) with `--also "<glob>"`, then persist chosen ones with `principles add-guidance-search-path "<glob>"`.

## Create, reshape, or remove

- Compare candidates against existing maps first: extend one with `add-member` or create a distinct map with `create-principle` + `add-member` (use `--section`, `--starting-at`/`--ending-at`, `--query`, and `--check` as needed).
- Reshape an existing map using `show-principle ID` with `change-description`, `change-activation`, `add-member`, `move-member`, `change-member-role`, `change-member-check`, `remove-member-check`, or `remove-member`.
- Remove an obsolete map with `principles remove-principle ID` (`--confirm` only if protected by its current audit and deactivation is intended). Member files and audit history stay readable via `show-audit ID`; never reuse a removed ID.
- Commit `.principles/maps/` before running the first audit (see [auditing-principles.md](auditing-principles.md)).
