# Creating and managing principles

Use this workflow to survey a repository's guidance, map new principles, reshape existing maps, or retire obsolete ones.

## 1. Survey guidance first

Run `principles list-principles` from the project root (or pass `--project PATH` in a monorepo) and follow its `next_action`.

- With nothing mapped yet, run `principles list-candidate-files` and show the user a table of candidate principles (name, one-line description, carrying files/sections) before writing any maps.
- With maps already present, use `principles list-candidate-files --commits-after REV` to spot principles in new or recently changed guidance.

### OpenCode discovery paths

`principles list-candidate-files` automatically discovers `AGENTS.md`, `CLAUDE.md`, `.claude/*`, `.agents/skills/`, and `.codex/*`.

- To preview OpenCode or repo-specific locations (such as `.opencode/**`, `.opencode/agents/*.md`, `REVIEW.md`, `opencode/commands/*.md`, or `.github/workflows/*`) during a read-only survey, repeat `--also "<glob>"`.
- After showing the candidate table, persist chosen globs with `principles add-guidance-search-path "<glob>"` (or drop one with `remove-guidance-search-path`).

## 2. Create or extend maps

Compare each candidate rule against existing maps before creating a new one:

- **Extend an existing principle:** `principles add-member ID PATH [--section HEADING] [--starting-at TEXT [--ending-at TEXT]] [--query '$.FIELD'] --role ROLE [--check COMMAND]`
- **Create a new principle:**
  1. `principles create-principle ID --description "What the principle is and why it matters"` (lower-kebab-case ID).
  2. Add every carrier with `add-member` (one command per member). Narrow passages inside larger sections with `--starting-at` / `--ending-at`, or frontmatter fields with `--query`.
  3. Attach `--check COMMAND` where an executable command enforces the member (e.g., a focused test suite or validator).
  4. Watch `mapped_elsewhere` warnings when two principles share lines and make sure each role explains its distinct concern.

## 3. Reshape or remove maps

- Inspect current members: `principles show-principle ID`.
- Update metadata or locators: `change-description`, `change-activation`, `move-member`, `change-member-role`, `change-member-check`, `remove-member-check`, `remove-member`.
- Retire an obsolete map: `principles remove-principle ID` (add `--confirm` only if protected by its current audit entry and deactivation is intended). Member files and audit history remain preserved and readable via `principles show-audit ID`. Never reuse a removed ID for a different principle.

## 4. Commit and run the first audit

In git, commit `.principles/maps/` (and `.principles/guidance-search-paths.json` if updated) before running the first full audit — `start-audit` refuses uncommitted maps. Then follow [auditing-principles.md](auditing-principles.md).
