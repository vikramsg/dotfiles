# Custom Bin Scripts

This directory contains custom scripts for the dotfiles environment.

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
