# Implementation notes: dotfiles.nav-wrap

Plan: `.agents/plans/herdr-nav-wrap.md` (frozen; deviations live here).

## What was built

Local Herdr plugin `herdr/plugin/nav_wrap/` (`dotfiles.nav-wrap`) that wraps
Ctrl+h/j/k/l at pane edges, sharing one `focus-wrap.sh` between the Herdr action
and the Neovim adapter.

## Decisions not already agreed

- **Dropped upstream's `HERDR_NAV_PASSTHROUGH_RE`.** The upstream plugin
  supported opt-in passthrough for other TUIs. Nothing in this repo sets it, and
  it was extra branching in the "is this Vim?" check. Removed rather than ported.
- **Kept the tmux fallback in `editor/nvim.lua`.** This is pre-existing behavior
  from the plugin being replaced, not a new compatibility shim.
- **Kept upstream's shell tradeoff.** `Ctrl+K`/`Ctrl+L` remain shadowed in
  non-Vim panes; not changed.
- **Plugin owns link/unlink/test in its own justfile.** Root `herdr` delegates to
  it, per the repo's "root justfile delegates" guideline.
- **`link` uninstalls `vim-herdr-navigation`.** The recipe drops the pinned
  GitHub install, so the old managed plugin would otherwise linger unused.
- **`~/.config/herdr-nav-wrap` anchor.** `herdr plugin link` canonicalises its
  argument, so the machine-local registry stores the repo path regardless; the
  anchor gives every committed reference a home-based path and matches how
  `zsh/.zshrc` / `tmux/tmux.conf` reach sibling scripts.
- **Neovim loads the adapter through the anchor.** `nvim/init.lua` now does
  `dofile(~/.config/herdr-nav-wrap/editor/nvim.lua)`. This makes the adapter
  depend on `just herdr` having run; there is no guarded fallback (no shim).
- **Wrap uses repeated opposite-direction focus.** As agreed, this reuses Herdr's
  spatial geometry instead of recomputing layout rects, at the cost of one CLI
  call per pane crossed. Single-pane presses make two no-op calls.
- **Added a `jq`-absent branch to `focus-wrap.sh`.** Reviewer flagged that the
  unconditional `jq` use makes a successful first move look like an edge and then
  performs an unintended opposite move; it also contradicted the documented
  "movement still works without jq". The guard now does one plain directional
  move when `jq` is missing. This is dependency handling for a real wrong-move
  bug, not a compatibility shim.
- **Tests use a mock `herdr`.** The mock is driven by an explicit transition
  table, so the tests assert the focus calls issued for each scenario. No
  change-detection tests, and the real-TTY checks are left manual.

## Scope and environment notes

- The live `just herdr` / `herdr plugin link` / upstream uninstall were **not**
  run: the user's `~/.config/herdr` is in active use and its `config.toml` still
  points at the old action ids. Wiring is validated by manifest/fixture tests
  only.
- A temporary `~/.config/herdr-nav-wrap` symlink was created to run the full
  Neovim suite, then removed.
- Live verification was run in an isolated named session, not the user's
  session: `herdr --session navwrap-test server` + a 3-pane row, running the real
  `focus-wrap.sh` inside the real panes. Wrap-left from leftmost → rightmost,
  normal-left from rightmost → middle, wrap-right from rightmost → leftmost, and
  single-pane-left → unchanged all passed. The session was deleted and the
  background server exited. The plugin manifest was also linked, enumerated
  (`down/left/right/up`), and unlinked against the real binary.
- Still human-only and **not** done: real `Ctrl+hjkl` keypresses, `Ctrl+H` vs
  Backspace under the kitty keyboard protocol, and tmux-inside-Herdr.
- `tests.git_review_spec` and `tests.pr_review_spec` fail identically on `main`
  (confirmed baseline); unrelated to this change.

## What should be reviewed

1. **Wrap semantics.** Does "walk the opposite direction to the far edge" match
   what you want in non-linear layouts? The tests cover row and grid fixtures;
   manual TTY checks are still needed for feel and for `Ctrl+H` vs Backspace.
2. **Anchor decision.** Confirm the `~/.config/herdr-nav-wrap` anchor is the
   intended home reference, and that `nvim/init.lua` depending on it (rather than
   a repo-relative path) is acceptable.
3. **`link` uninstalling upstream.** Confirm the recipe should remove
   `vim-herdr-navigation` automatically.
4. **Location.** `herdr/plugin/nav_wrap/` intentionally departs from the
   `bin/<tool>/` convention per the agreed plan; confirm that exception is still
   wanted.
5. **Dropped passthrough regex.** Confirm you don't rely on
   `HERDR_NAV_PASSTHROUGH_RE` for lazygit/k9s/etc.
