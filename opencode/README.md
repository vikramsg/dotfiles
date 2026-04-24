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


### Permissions

Notice that we have to do `/private/tmp`.
This is because on MacOs `/tmp` is actually a symlink from `/private/tmp`.
So, if we specify only `/tmp` then the agent will still ask for permissions on Mac.  

Specifying `dir: allow` actually gives `All` permissions on that dir to the agent.
But it is restricted by any denies etc settings in your workspace.

```yml
  external_directory:
    "/tmp/**": "allow"
    "/private/tmp/**": "allow"
```

## State

Opencode stores files under

```
~/.local/state/opencode
~/.local/share/opencode
~/.config/opencode
```

### Persistent orchestration state install contract

The orchestration state integration is loaded from the installed config path, not from this repo checkout directly.

- `~/.config/opencode/opencode.json` contains `./plugins/orchestration-state.js`.
- OpenCode resolves that relative path from `~/.config/opencode/`.
- If `~/.config/opencode/plugins/orchestration-state.js` is missing, the plugin never loads and `.agents/tasks` is never created.
- `~/.config/opencode/rules.md` is still part of the normal installed config layout because `opencode.json` references it in `instructions`, but orchestration-state persistence does not depend on that file being present.
- OpenCode plugin/config changes only apply to newly started OpenCode processes.
- If you already have an already-running OpenCode session, rerun `just opencode` and then restart that session before checking persistence again.
- This repo currently documents the explicit restart contract; hot reload is not assumed here.

Whenever you add or change OpenCode plugins in this repo, rerun:

```bash
just opencode
```

To verify the live installed layout from an arbitrary worktree, run:

```bash
just opencode-doctor
```

That smoke check fails explicitly if the installed plugin path is missing. It then runs `opencode run --command orchestrate ...` against a temporary worktree and confirms that the installed environment creates `.agents/tasks/index.json` plus a persisted `state.json`. After artifact verification, only `opencode run` exit status `0` and the timeout status `124` are accepted; any other non-zero exit fails the smoke check.

## Favorite Models

OpenCode does not currently support declaring favorite models in `opencode.json`.

- Use `opencode.json` to set the default startup model.
- Use `tui.json` to bind favorite cycling keys.
- Use the TUI model picker to mark models as favorites.

### Recommended setup

Set a default model in `opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "azure-openai/gpt-5-4"
}
```

Bind left and right to cycle favorite models in `tui.json`:

```json
{
  "$schema": "https://opencode.ai/tui.json",
  "keybinds": {
    "model_cycle_favorite": "<leader>right",
    "model_cycle_favorite_reverse": "<leader>left"
  }
}
```

### How to add favorites

1. Open OpenCode.
2. Run `/models`.
3. Highlight the model you want in the rotation.
4. Press `Ctrl+F` to toggle it as a favorite.

Favorite models are stored by OpenCode in local TUI state, not in `opencode.json`.

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

## Auth


Helpful commands

```bash
# To setup auth for provider, mcp etc.
# Auth usually saved in ~/.local/share/opencode/auth.json
opencode auth login
```

For custom providers, once the provider is setup in `opencode.json`,
open the TUI and then do `/connect`.
The provider should be available under `Other`.
Enter your key there.


### OpenAI

To connect to OpenAI via `oauth` which is how Codex connects to it,
do `opencode auth login` but from a system where the browser has access to your terminal.

Note also that the plugin `"opencode-websearch-cited@1.2.0"` messes with this so for the login process, remove that plugin and add it back after finishing. 

Inside the login dropdown, select `OpenAI - ChatGPT Plus (browser)` and then login to the browser.

Once you have the login finished, open `~/.local/share/opencode/auth.json` and copy the `openai` section to the same file on your VM.

## Ref

- [OpenCode Github](https://github.com/anomalyco/opencode)
- [OpenCode Docs](https://opencode.ai/docs)
- [OpenCode Config Schema](https://opencode.ai/config.json)
