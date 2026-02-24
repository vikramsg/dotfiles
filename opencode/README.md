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

## Custom Instructions & Rules (`rules.md`)

This repository includes a `rules.md` file designed to provide base system instructions to the OpenCode AI that apply across all sessions. 

### What it does
By default, this file contains a hard rule telling the AI to **never delete `.sqlite` or `.db` files**.

### How it is configured
This file is injected into the AI's context using the `instructions` array inside `opencode.json` (and `yolo.json`):

```json
{
  "instructions": [
    "~/.config/opencode/rules.md"
  ]
}
```

### Safety & Permissions Fallback
In addition to prompting the AI via `rules.md`, `opencode.json` enforces this at the execution level using OpenCode's permissions system:

```json
{
  "permission": {
    "bash": {
      "*rm *.sqlite*": "deny",
      "*rm *.db*": "deny"
    }
  }
}
```
*Note: Because we only specify `deny` rules for specific file patterns, OpenCode automatically falls back to its default behavior (`ask`) for all other `bash` commands. This safely adds a constraint without overriding your entire default permission configuration.*

## Inspecting the Internal System Prompt

If you want to read the exact system instructions and tool definitions OpenCode uses behind the scenes, you can extract them from the local log files.

The system prompt is embedded inside the JSON payloads sent to the LLM API and starts with `"You are opencode, an interactive CLI agent..."`.

### How to extract it
To extract the raw system prompt from your most recent log file and save it as readable text, run this command:

```bash
LATEST_LOG=$(ls -t ~/.local/share/opencode/log | head -n 1)
grep -o '{"parts":\[{"text":"You are opencode.*' ~/.local/share/opencode/log/$LATEST_LOG | head -n 1 | sed 's/^[^{]*//' | sed 's/}$//' | jq -r '.parts[0].text' > /tmp/opencode_prompt.txt
cat /tmp/opencode_prompt.txt
```
*(Note: Because the log lines contain massive JSON arrays for the API request, we use `grep -o` and some text manipulation to isolate just the system prompt string).*

