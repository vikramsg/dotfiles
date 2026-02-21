# OpenCode Tips & Configuration

This repository tracks configuration and learnings about the `opencode` CLI agent.

## Configuration Modes

OpenCode operates based on the configuration defined in `opencode.json` (by default). This dictates the AI's permissions for reading, editing, and executing terminal commands.

### Standard Mode (Ask Permissions)
By default, OpenCode operates in an interactive "Ask" mode. When the AI wants to execute a tool (like `bash` or `edit`), it will pause and prompt for permission.

*   `Enter`: Accept Once
*   `a`: Accept Always (Auto-approves *that specific tool* for the remainder of the session)
*   `Esc`: Reject

### YOLO Mode (Auto-Approve / Always Allow)
OpenCode does **not** currently have a built-in runtime shortcut (like `Ctrl+Y`) to globally toggle YOLO mode on and off in the middle of a session (though it is a highly requested feature currently tracked in GitHub issues like #1813 and #11831).

To achieve a true "YOLO mode" where OpenCode can run autonomously without any permission prompts, you must configure the permissions to `"allow"` *before* starting the session.

#### Setting up a YOLO Profile

Instead of permanently altering your default `opencode.json` to be unsafe, you can use the `OPENCODE_CONFIG` environment variable to launch a specific configuration file on demand.

1.  **Use the YOLO config file (`yolo.json`):**
    This dotfiles repository contains a `yolo.json` configuration file ready to use. Symlink it to your config directory:
    ```bash
    ln -s ~/Projects/Personal/dotfiles/opencode/yolo.json ~/.config/opencode/yolo.json
    ```

2.  **Launch OpenCode with the YOLO config:**
    ```bash
    OPENCODE_CONFIG=~/.config/opencode/yolo.json opencode
    ```

3.  **Create a shell alias (Recommended):**
    Add this to your `~/.bashrc` or `~/.zshrc` to make launching YOLO mode effortless:
    ```bash
    alias opencode-yolo='OPENCODE_CONFIG="$HOME/.config/opencode/yolo.json" opencode'
    ```

Now you can run `opencode` for normal safe operations, and `opencode-yolo` when you want the AI to execute fully autonomously.

## Future Updates
*Note: The OpenCode team is actively working on PRs (like #11831) to introduce native `--yolo` flags, `OPENCODE_YOLO=true` environment variables, and UI toggles for a formal YOLO mode in future releases.*
