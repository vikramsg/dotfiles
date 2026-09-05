# Custom Bin Scripts

This directory contains custom scripts for the dotfiles environment.

## Python Tools (uv)

Install tools from this repo with `uv`:

```bash
uv tool install ./bin/ghostty_workspace --force
uv tool install ./bin/screenshot --force
uv tool install ./bin/lch --force
uv tool install ./bin/opener_tunnel --force
uv tool install ./bin/ocint --force
uv tool install ./bin/gh_stats --force
```

Native tools with package-local build recipes are installed with `just`:

```bash
just macflow
```

Upgrade an installed local tool after changes:

```bash
uv tool install ./bin/ghostty_workspace --force --no-cache
uv tool install ./bin/screenshot --force --no-cache
uv tool install ./bin/lch --force --no-cache
uv tool install ./bin/opener_tunnel --force --no-cache
uv tool install ./bin/ocint --force --no-cache
uv tool install ./bin/gh_stats --force --no-cache
```

Each tool keeps its own package-local tests under `bin/<tool>/tests`.

## macflow

Native macOS automation host and HTTP CLI for configured layouts, screenshot
capture, overlays, and the draggable screenshot shelf.

- Install: `just macflow`
- Test: `just --justfile bin/macflow/justfile test`
- Docs: `bin/macflow/README.md`, `macflow/README.md`

Run all Python tests from repo root:

```bash
uv run --all-packages --group dev pytest
```

## screenshot

Canonical screenshot-domain tool for screenshot config, macOS screenshot location, clipboard history, and sync workflows.

- Install: `uv tool install ./bin/screenshot --force`
- Test: from `bin/screenshot`, run `uv run pytest`
- Docs: `bin/screenshot/README.md`, `screenshot/README.md`

## lch

Thin native lifecycle adapter that installs and manages launchd/systemd watchers and configured services.

- Install: `uv tool install ./bin/lch --force`
- Test: from `bin/lch`, run `uv run pytest`
- Docs: `bin/lch/README.md`, `lch/README.md`

## ghostty-workspace

Open a Ghostty window with tabs/commands/directories from a TOML workspace config.

Requires `window-new-tab-position = end` in `ghostty/config` for deterministic tab append order during scripted startup.

- Install: `uv tool install ./bin/ghostty_workspace --force`
- Test: from `bin/ghostty_workspace`, run `uv run pytest`
- Docs: `bin/ghostty_workspace/README.md`

## ocint

Read-only local OpenCode SQLite usage analytics and history search.

- Install: `uv tool install ./bin/ocint --force --no-cache`
- Test: from repo root, run `uv run --package ocint pytest`
- Docs: `bin/ocint/README.md`
- Safety: commands open the SQLite database with `mode=ro`; use `OPENCODE_DB` or `--db` to point at a temporary DB for verification.

## gh-stats

Summarize merged pull requests by week, repository, or both using the authenticated GitHub CLI.

- Install: `just gh-stats`
- Test: from repo root, run `uv run --package gh-stats pytest bin/gh_stats/tests`
- Docs: `bin/gh_stats/README.md`

## opener-tunnel and xdg-open

Run `just opener-tunnel` on the Mac to install the config-driven listener and
LCH service. The service uses the existing private `vm` SSH alias and keeps the
live SSH process inspectable in tmux. The VM-side `xdg-open` wrapper continues
to send one newline-terminated URL to `~/.opener.sock`.

See `bin/opener_tunnel/README.md` and `opener_tunnel/config.toml`.

---

## gocat

High-performance Go terminal image renderer using Kitty graphics protocol (`t=f` fast path and `t=d` streaming fallback).

- Build: `cd bin/gocat && go build -o gocat .`
- Test: `cd bin/gocat && go test ./...`
- Docs: `bin/gocat/README.md`, `bin/gocat/EXPERIMENT_LOG.md`

---

## lc

A wrapper for `ls`/`eza` and `cat`/`bat` that provides a consistent file/directory preview experience.
