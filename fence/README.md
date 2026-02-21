# Fence Configuration

This directory contains configuration for [Fence](https://github.com/Use-Tusk/fence), an OS-level sandbox used to safely run AI CLI agents like OpenCode in autonomous ("YOLO") mode.

## Why Use Fence with OpenCode?

OpenCode's internal permission system is software-enforced. When you enable YOLO mode (auto-approve all tools), you are trusting the AI not to hallucinate destructive commands (`rm -rf /`, `git push --force`) or read sensitive credentials.

Fence provides a defense-in-depth layer by wrapping the OpenCode process at the OS level (`sandbox-exec` on macOS, `bubblewrap` on Linux). It enforces strict boundaries regardless of OpenCode's internal permissions.

## Built-in Protections (via the `code` template)

Fence's default `code` template provides the following protections out of the box:

*   **Network Isolation:** Blocks all outbound traffic except explicitly allowed LLM endpoints, GitHub, and package registries. Blocks cloud metadata IPs to prevent credential theft.
*   **Filesystem Restrictions:** Restricts writes to the current workspace and `/tmp`.
*   **Secret Protection:** Strictly denies reading from `~/.ssh/`, `~/.aws/`, `~/.docker/`, and `~/.config/gh/`. Denies writing to `.env` and `.key/.pem` files.
*   **Command Blocking:** Intercepts and blocks dangerous commands like `sudo`, `git push`, `npm publish`, and `gh pr create`.

## Setup Instructions

### 1. Install Fence

**macOS (Homebrew):**
```bash
brew tap use-tusk/tap
brew install use-tusk/tap/fence
```

### 2. Configure Fence for OpenCode

We use a custom configuration (`opencode.json`) that extends Fence's built-in `code` template.

Symlink this configuration to your local Fence config directory:

```bash
mkdir -p ~/.config/fence
ln -s ~/Projects/Personal/dotfiles/fence/opencode.json ~/.config/fence/opencode.json
```

### 3. Create the Sandboxed YOLO Alias

To run OpenCode in YOLO mode *inside* the Fence sandbox, add this alias to your `~/.bashrc` or `~/.zshrc`:

```bash
# Safely run OpenCode in full autonomous YOLO mode inside a strict OS sandbox
alias opencode-yolo-safe='OPENCODE_CONFIG="$HOME/Projects/Personal/dotfiles/opencode/yolo.json" fence --settings "$HOME/.config/fence/opencode.json" -- opencode'
```

*(Note: This assumes you have already set up the `yolo.json` config as described in the `opencode` directory).*

### 4. Auditing Mode (Optional)

If you want to see exactly what OS-level violations Fence is blocking while the AI operates autonomously, you can run Fence in monitor mode (`-m`):

```bash
alias opencode-yolo-audit='OPENCODE_CONFIG="$HOME/Projects/Personal/dotfiles/opencode/yolo.json" fence -m --settings "$HOME/.config/fence/opencode.json" -- opencode'
```
