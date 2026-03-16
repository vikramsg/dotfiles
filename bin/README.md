# Custom Bin Scripts

This directory contains custom scripts for the dotfiles environment.

## Python Tools (uv)

Install tools from this repo with `uv`:

```bash
uv tool install ./bin/screenshot_sync --force
uv tool install ./bin/ghostty_workspace --force
uv tool install ./bin/screenshot --force
uv tool install ./bin/lch --force
```

Upgrade an installed local tool after changes:

```bash
uv tool install ./bin/screenshot_sync --force --no-cache
uv tool install ./bin/ghostty_workspace --force --no-cache
uv tool install ./bin/screenshot --force --no-cache
uv tool install ./bin/lch --force --no-cache
```

Each tool keeps its own package-local tests under `bin/<tool>/tests`.

Run all Python tests from repo root:

```bash
uv run pytest
```

## screenshot-sync

Event-driven screenshot sync from macOS to a remote host via `launchd` + `rsync`.

- Install: `uv tool install ./bin/screenshot_sync --force`
- Test: from `bin/screenshot_sync`, run `uv run pytest`
- Docs: `bin/screenshot_sync/README.md`

## screenshot

Canonical screenshot-domain tool for screenshot config, clipboard history, and sync workflows.

- Install: `uv tool install ./bin/screenshot --force`
- Test: from `bin/screenshot`, run `uv run pytest`
- Docs: `bin/screenshot/README.md`, `screenshot/README.md`

## lch

Thin `launchd` orchestrator that installs, manages, and dispatches LaunchAgents into domain CLIs.

- Install: `uv tool install ./bin/lch --force`
- Test: from `bin/lch`, run `uv run pytest`
- Docs: `bin/lch/README.md`, `lch/README.md`

## ghostty-workspace

Open a Ghostty window with tabs/commands/directories from a TOML workspace config.

Requires `window-new-tab-position = end` in `ghostty/config` for deterministic tab append order during scripted startup.

- Install: `uv tool install ./bin/ghostty_workspace --force`
- Test: from `bin/ghostty_workspace`, run `uv run pytest`
- Docs: `bin/ghostty_workspace/README.md`

## xdg-open (Remote Browser Proxy)

This script allows you to open URLs from this remote VM directly in your local Mac's web browser. It is designed to be used with the `opener` tool and SSH remote forwarding.

### Local Setup (On your Mac)

1. **Install Opener**:
   ```bash
   brew install superbrothers/opener/opener
   brew services start opener
   ```

2. **Configure SSH**:
   Add the following to your `~/.ssh/config` on your Mac:
   ```sshconfig
   Host <your-vm-hostname>
     RemoteForward /path/to/home/.opener.sock /Users/<your-mac-user>/.opener.sock
   ```
   *Replace `<your-mac-user>` with your actual local username.*

3. **SSH Server Tweak (Optional but recommended)**:
   If you experience issues with stale sockets, add this to the VM's `/etc/ssh/sshd_config` (requires sudo):
   ```text
   StreamLocalBindUnlink yes
   ```

### Usage

Once configured, any tool that uses `xdg-open` (like `gh browse`, `lazygit`, or Neovim's `gx`) will automatically trigger your local browser.

The script is OS-aware:
- **On Linux**: It attempts to use the Unix socket bridge.
- **On macOS**: It falls back to the native `open` command.

---

## lc

A wrapper for `ls`/`eza` and `cat`/`bat` that provides a consistent file/directory preview experience.
