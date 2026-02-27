# Tmux Setup Guide

This directory contains the configuration files for Tmux, a terminal multiplexer.

## Prerequisites & macOS Compatibility Note

macOS ships with an outdated version of Bash (`bash 3.2.57`) due to GPLv3 licensing issues. Many modern Tmux plugins and themes (such as `janoamaral/tokyo-night-tmux` and `fabioluciano/tmux-powerkit`) rely on features introduced in newer versions of Bash (specifically associative arrays `declare -A` and global declarations `declare -g`).

If you are using macOS, **you must install a modern version of bash** for these themes to load their color palettes correctly. If you do not upgrade bash, the theme scripts will crash silently or fallback to default, often ugly, colors (e.g., a solid mustard yellow background).

### Installing Modern Bash

You can install a modern version of Bash using Homebrew. This will not change your default interactive shell (which remains `zsh`), but it will make modern bash available in your `PATH` for scripts to use.

```bash
brew install bash
```

After installing, you **must restart the tmux server** completely for it to pick up the new bash executable.

1. Save your sessions (if using `tmux-resurrect`): `<prefix> + Ctrl-s`
2. Kill the server: `tmux kill-server`
3. Restart tmux: `tmux`
4. Restore your sessions: `<prefix> + Ctrl-r`

## Current Setup

*   **Plugin Manager:** TPM (`~/.tmux/plugins/tpm`)
*   **Theme:** `janoamaral/tokyo-night-tmux` (Configured for a Lualine-style "bubbles/powerline" aesthetic with the 'night' variant).
*   **Session Management:** `tmux-resurrect` & `tmux-continuum`
*   **Navigation:** `vim-tmux-navigator` (Seamless navigation between Neovim splits and Tmux panes).

### Managing Plugins

1.  Add new plugin to `~/.tmux.conf` with `set -g @plugin '...'`
2.  Press `prefix` + `I` (capital i) to install plugins.
3.  Press `prefix` + `U` to update plugins.
4.  Press `prefix` + `alt` + `u` to remove/uninstall plugins not on the plugin list.

## Testing Configuration Changes

Before applying changes to your main `tmux.conf`, you can test them safely in an isolated environment without affecting your running sessions. This is highly recommended to prevent breaking your daily workflow.

1. **Create a temporary configuration file**:
   Copy your proposed changes or your current `tmux.conf` to a temporary location.
   ```bash
   cp ~/.tmux.conf /tmp/tmux-test.conf
   # Make your experimental edits to /tmp/tmux-test.conf
   ```

2. **Start a sandboxed Tmux server**:
   Use a different socket name (`-L`) and point to your temporary config file (`-f`). This creates a completely separate Tmux instance.
   ```bash
   tmux -L test_socket -f /tmp/tmux-test.conf
   ```

3. **Verify the changes**:
   Test your new keybindings, visual changes, or status bar updates in this isolated session.

4. **Exit the sandbox**:
   Once you are done testing, simply exit the Tmux session. The `test_socket` server will close automatically.
   ```bash
   exit
   ```

5. **Apply the changes**:
   If the tests are successful, you can confidently apply the changes to your actual `~/Projects/Personal/dotfiles/tmux/tmux.conf`.