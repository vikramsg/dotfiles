# Plan: Migrate Hunk Review Launcher to Zsh Function

## Context & Goal

Remove the standalone `bin/hunk-review` package and integrate the smart review-launch logic (`working-tree` vs `main...HEAD` vs `no-changes`) directly into `zsh/.zsh_script` as a native shell function.

---

## Proposed Changes

### 1. `zsh/.zsh_script`
Add `hunk-review()` shell function at the end of the script:
- Resolves Git root and navigates there.
- Checks `git status --porcelain`: if dirty, sets `HUNK_REVIEW_TARGET=working` and runs `exec hunk diff --mode stack`.
- Checks `main...HEAD`: if clean, prints message and exits `0`.
- Otherwise sets `HUNK_REVIEW_TARGET=main` and runs `exec hunk diff main... --mode stack`.

### 2. `herdr/config.toml`
Update keybinding `prefix+shift+d`:
- Change `command = "hunk-review"` to `command = 'zsh -ic "hunk-review"'`.

### 3. Remove `bin/hunk-review/` Package
Delete the following files:
- `bin/hunk-review/hunk-review`
- `bin/hunk-review/justfile`
- `bin/hunk-review/README.md`
- `bin/hunk-review/tests/test_hunk_review.py`
- Stale symlink: `~/.local/bin/hunk-review`

### 4. `justfile`
- Remove `hunk-review-install` private recipe.
- Remove dependency on `hunk-review-install` from `hunk:`.
- Wire `hunk-test:` recipe directly to `bun test hunk/tests/review-workflow.test.ts`.

### 5. `hunk/README.md`
- Update setup and usage notes: launcher is provided via Zsh (`zsh/.zsh_script`), not `~/.local/bin/`.

---

## Verification Steps

1. **Syntax & Tests:**
   - `zsh -n zsh/.zsh_script`
   - `bun test hunk/tests/review-workflow.test.ts`
   - `HERDR_CONFIG_PATH="$PWD/herdr/config.toml" herdr config check`
2. **Interactive Testing:**
   - Source `zsh/.zsh_script` in current shell.
   - Run `hunk-review` in a dirty repo -> opens working tree.
   - Run `hunk-review` on a clean feature branch -> opens `main...`.
   - Run `hunk-review` on clean `main` -> prints message and exits 0.
3. **Herdr Popup Testing:**
   - Trigger `prefix+Shift+D` via Herdr -> verify popup executes `zsh -ic "hunk-review"` cleanly.
