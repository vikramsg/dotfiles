# dotfiles.nav-wrap

A local Herdr plugin that makes `Ctrl+h/j/k/l` navigation wrap around at pane
edges, the way tmux's `select-pane -L/-R/-U/-D` does. Neovim split movement and
the tmux fallback keep working underneath it.

## How it works

- Herdr binds the four direct Ctrl chords to this plugin's `left/down/up/right`
  actions (`herdr/config.toml`).
- `navigate.sh` forwards the chord into the focused pane when Vim/Neovim is the
  foreground process, so the editor owns movement between its own splits.
- Otherwise it calls `focus-wrap.sh`, which moves one pane in the requested
  direction. If the pane is already at that edge, it walks the opposite
  direction to the far edge and leaves focus there.
- At a Neovim split edge, `editor/nvim.lua` calls the same `focus-wrap.sh`, so
  exiting Neovim wraps too.

`focus-wrap.sh` reuses Herdr's own spatial movement instead of reimplementing
layout geometry, so non-uniform and grid layouts resolve the same way native
navigation does.

## Linking

`just herdr` creates the home anchor and registers the plugin:

```
~/.config/herdr-nav-wrap -> <repo>/herdr/plugin/nav_wrap
herdr plugin link ~/.config/herdr-nav-wrap
```

`herdr plugin link` canonicalises the anchor, so Herdr's machine-local registry
stores the repo path. That is per-machine runtime state created by the justfile;
no committed file hardcodes an absolute path.

## Tests

```sh
just --justfile herdr/plugin/nav_wrap/justfile test
```

Shell tests use `tests/mock-herdr.sh` and assert the focus calls issued for
normal movement, edge wrap, single-pane, grid, and Vim forwarding.
`tests/nvim.lua` runs headless and covers the editor adapter plus the tmux
fallback.
