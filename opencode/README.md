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

## Dual Mode Models (Plan vs. Build)

OpenCode utilizes a dual-mode workflow:
1.  **Plan Mode (Read-Only):** The AI analyzes code and proposes a strategy.
2.  **Build Mode (Execution):** The AI writes code and executes commands based on the approved plan.

*(You can toggle between these modes instantly in the terminal by pressing the **Tab** key.)*

You can optimize cost and performance by configuring different models for each mode within your `opencode.json` configuration file under the `"agent"` key.

### Configuration Example
To use a fast, inexpensive model for planning, and a more capable model for building, add the following to your configuration:

```json
{
  "agent": {
    "plan": {
      "model": "anthropic/claude-3-haiku",
      "temperature": 0.1,
      "tools": {
        "write": false,
        "edit": false,
        "bash": false
      }
    },
    "build": {
      "model": "anthropic/claude-3-5-sonnet",
      "temperature": 0.3,
      "tools": {
        "write": true,
        "edit": true,
        "bash": true
      }
    }
  }
}
```
*Note: Disabling the `write`, `edit`, and `bash` tools in Plan Mode ensures the AI cannot accidentally modify your system while planning.*

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


## MCP

Setup MCP by adding config like this to the config JSON file.
MIRO for example, required OAUTH, but it did not automatically open the browser when I added to the config.
I had to do `opencode mcp auth miro-mcp`. 
This opened a page on a specific port which I needed to add to the port forwarding for ssh as well.

```json
  "mcp": {
    "miro-mcp": {
      "type": "remote",
      "url": "https://mcp.miro.com/",
      "enabled": true
    }
  }
```

### Miro

Note that when using the Miro MCP, we authenticated to a Team.
The MCP only has access to the team board.
Miro makes it very hard to correctly deal with this, but here's the steps.

1. Make sure you did create the team and that you know which team the MCP has access to.
    - This can be done by `click on profile -> select team in dropdown -> click on apps -> check MCP server is there`. 
    - Now go back to board view, create board.
    - This board by default will be put on your personal account. 
    - Go to 3 dots at top left, `click -> Board -> move to -> Team`.
    - Then this will be available to your agent!
