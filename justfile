# NOTE: Guardrail for just recipes in this repo:
# - Use $VAR for shell variable references.
# - Use $(...) for command substitution.
# - Do NOT use $$VAR for variable references.
# - $$ expands to shell PID and can corrupt paths (for example 721854CONFIG_FILE).
# - Use {{...}} only for just-level interpolation.

# List available commands
default:
    @just --list

# Bootstrap Homebrew and install tools from Brewfile
brew:
    @echo "Ensuring Homebrew is installed..."
    @if ! command -v brew > /dev/null; then \
        echo "Homebrew not found. Installing..."; \
        NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"; \
    fi
    @if [ -x /opt/homebrew/bin/brew ]; then \
        eval "$(/opt/homebrew/bin/brew shellenv)"; \
    elif [ -x /home/linuxbrew/.linuxbrew/bin/brew ]; then \
        eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"; \
    elif [ -x /usr/local/bin/brew ]; then \
        eval "$(/usr/local/bin/brew shellenv)"; \
    fi; \
    brew bundle check --file "{{justfile_directory()}}/Brewfile" || brew bundle --file "{{justfile_directory()}}/Brewfile"

# Set up Neovim symlink
nvim:
    @echo "Setting up Neovim symlink..."
    mkdir -p ~/.config
    ln -sfn {{justfile_directory()}}/nvim ~/.config/nvim
    @echo "Neovim symlink created at ~/.config/nvim -> {{justfile_directory()}}/nvim"
    @if ! command -v marxual &> /dev/null; then \
        echo "Installing marxual for markdown previews..."; \
        just marxual; \
    else \
        echo "marxual is already installed."; \
    fi

# Set up Tmux symlink
tmux:
    @echo "Setting up Tmux symlink..."
    mkdir -p ~/.config
    ln -sfn {{justfile_directory()}}/tmux ~/.config/tmux
    @echo "Tmux symlink created at ~/.config/tmux -> {{justfile_directory()}}/tmux"
    @if [ ! -d ~/.tmux/plugins/tpm ]; then \
        echo "Installing Tmux Plugin Manager (TPM)..."; \
        git clone https://github.com/tmux-plugins/tpm ~/.tmux/plugins/tpm; \
    else \
        echo "TPM is already installed."; \
    fi

# Set up Opencode symlink
opencode:
    @echo "Setting up Opencode symlink..."
    mkdir -p ~/.config
    mkdir -p ~/.config/opencode
    ln -sfn {{justfile_directory()}}/opencode/opencode.json ~/.config/opencode/opencode.json
    ln -sfn {{justfile_directory()}}/opencode/tui.json ~/.config/opencode/tui.json
    ln -sfn {{justfile_directory()}}/opencode/rules.md ~/.config/opencode/rules.md
    ln -sfn {{justfile_directory()}}/opencode/agents ~/.config/opencode/agents
    ln -sfn {{justfile_directory()}}/opencode/commands ~/.config/opencode/commands
    ln -sfn {{justfile_directory()}}/opencode/plugins ~/.config/opencode/plugins
    @echo "Opencode symlink created at ~/.config/opencode/opencode.json -> {{justfile_directory()}}/opencode/opencode.json"
    @echo "Opencode rules file symlinked to ~/.config/opencode/rules.md"
    @echo "Opencode agent directory symlinked to ~/.config/opencode/agents"
    @echo "Opencode commands directory symlinked to ~/.config/opencode/commands"
    @echo "Opencode plugins directory symlinked to ~/.config/opencode/plugins"
    @PLUGIN_FILE="$HOME/.config/opencode/plugins/orchestration-state.js"; \
        RULES_FILE="$HOME/.config/opencode/rules.md"; \
        if [ ! -e "$PLUGIN_FILE" ]; then \
            echo "ERROR: Missing installed OpenCode plugin at $PLUGIN_FILE"; \
            echo "This is an install/symlink problem, not an orchestration hook problem."; \
            exit 1; \
        fi; \
        if [ ! -e "$RULES_FILE" ]; then \
            echo "ERROR: Missing installed OpenCode rules file at $RULES_FILE"; \
            echo "This is an install/symlink problem, not an orchestration hook problem."; \
            exit 1; \
        fi; \
        echo "Verified OpenCode orchestration plugin at $PLUGIN_FILE"; \
        echo "Verified OpenCode rules file at $RULES_FILE"
    @echo "OpenCode plugin/config changes only apply to newly started OpenCode processes."
    @echo "If you have an already-running OpenCode session, restart it after running 'just opencode'."
    @echo "Run 'just opencode-doctor' to smoke-test persistence from an arbitrary worktree"

# Verify installed Opencode persistence from a non-repo worktree
opencode-doctor:
    @CONFIG_DIR="$HOME/.config/opencode"; \
        PLUGIN_FILE="$CONFIG_DIR/plugins/orchestration-state.js"; \
        if [ ! -e "$PLUGIN_FILE" ]; then \
            echo "ERROR: Missing installed OpenCode plugin at $PLUGIN_FILE"; \
            echo "Run 'just opencode' from {{justfile_directory()}} to refresh ~/.config/opencode."; \
            echo "This is an install/symlink problem, not an orchestration hook problem."; \
            exit 1; \
        fi; \
        TMPDIR=$(mktemp -d); \
        LOGFILE=$(mktemp); \
        timeout 60s opencode run --print-logs --command orchestrate --format json --dir "$TMPDIR" "Persistent-state smoke test only. Do not edit files; just acknowledge the request." >"$LOGFILE" 2>&1; \
        RUN_STATUS=$?; \
        node --input-type=module -e 'import fs from "node:fs"; import path from "node:path"; const root=process.argv[1]; const tasks=path.join(root, ".agents", "tasks"); const runs=fs.existsSync(tasks) ? fs.readdirSync(tasks).filter((entry) => entry !== "index.json") : []; if (!fs.existsSync(path.join(tasks, "index.json"))) { console.error(`Missing ${path.join(tasks, "index.json")}`); process.exit(1); } if (runs.length !== 1) { console.error(`Expected 1 persisted run, found ${runs.length}`); process.exit(1); } if (!fs.existsSync(path.join(tasks, runs[0], "state.json"))) { console.error(`Missing ${path.join(tasks, runs[0], "state.json")}`); process.exit(1); }' "$TMPDIR" || { \
            echo "ERROR: OpenCode orchestration persistence smoke check failed."; \
            echo "opencode run exit status: $RUN_STATUS"; \
            echo "See logs: $LOGFILE"; \
            exit 1; \
        }; \
        if [ $RUN_STATUS -eq 0 ]; then \
            echo "OpenCode CLI exited cleanly during smoke check."; \
        elif [ $RUN_STATUS -eq 124 ]; then \
            echo "OpenCode persistence smoke check passed after artifact verification, and opencode run timed out with status 124."; \
            echo "See logs for timeout diagnostics: $LOGFILE"; \
        else \
            echo "ERROR: OpenCode persistence smoke check passed artifact verification, but opencode run exit status was $RUN_STATUS."; \
            echo "See logs for CLI-exit diagnostics: $LOGFILE"; \
            exit 1; \
        fi; \
        echo "OpenCode persistence smoke check passed in $TMPDIR"


# Set up Ghostty symlink
ghostty:
    @echo "Setting up Ghostty symlink..."
    mkdir -p ~/.config/ghostty
    ln -sfn {{justfile_directory()}}/ghostty/config ~/.config/ghostty/config
    ln -sfn {{justfile_directory()}}/ghostty/workspaces ~/.config/ghostty/workspaces
    @echo "Ghostty symlink created at ~/.config/ghostty/config -> {{justfile_directory()}}/ghostty/config"
    @echo "Ghostty workspaces symlink created at ~/.config/ghostty/workspaces -> {{justfile_directory()}}/ghostty/workspaces"


# Set up screenshot config symlink, install tool, and apply macOS location
screenshot:
    @echo "Setting up screenshot config symlink and tool..."
    mkdir -p ~/.config/screenshot
    ln -sfn {{justfile_directory()}}/screenshot/config.json ~/.config/screenshot/config.json
    uv tool install ./bin/screenshot --force --no-cache
    @if [ "$(uname)" = "Darwin" ]; then \
        "$HOME/.local/bin/screenshot" macos apply; \
    fi
    @echo "screenshot config symlink created at ~/.config/screenshot/config.json -> {{justfile_directory()}}/screenshot/config.json"


# Set up lch config symlink and install tool
lch:
    @echo "Setting up lch config symlink and tool..."
    mkdir -p ~/.config/lch
    ln -sfn {{justfile_directory()}}/lch/config.json ~/.config/lch/config.json
    uv tool install ./bin/lch --force --no-cache
    @if [ "$(uname)" = "Linux" ]; then \
        "$HOME/.local/bin/lch" install lch-screenshot-clipboard; \
    fi
    @echo "lch config symlink created at ~/.config/lch/config.json -> {{justfile_directory()}}/lch/config.json"


# Set up custom bin symlinks
bin:
    @echo "Setting up custom bin symlinks..."
    mkdir -p ~/.local/bin
    ln -sfn {{justfile_directory()}}/bin/lc ~/.local/bin/lc
    @if [ "$(uname)" = "Linux" ]; then \
        ln -sfn {{justfile_directory()}}/bin/xdg-open ~/.local/bin/xdg-open; \
        echo "xdg-open symlink created at ~/.local/bin/xdg-open"; \
    fi

# Build and install marxual
marxual:
    @echo "Installing marxual..."
    @if ! command -v go > /dev/null; then \
        echo "Go is not installed. Run 'just brew' first."; \
        exit 1; \
    fi
    @mkdir -p ~/.local/bin && cd {{justfile_directory()}}/bin/marxual && GOBIN="$HOME/.local/bin" go install .
    @echo "marxual installed at ~/.local/bin/marxual"

# Set up lazygit symlink (Linux only)
lazygit:
    @if [ "$(uname)" = "Linux" ]; then \
        echo "Setting up lazygit symlink..."; \
        mkdir -p ~/.config/lazygit; \
        ln -sfn {{justfile_directory()}}/lazygit/config.yml ~/.config/lazygit/config.yml; \
        echo "lazygit symlink created at ~/.config/lazygit/config.yml"; \
    else \
        echo "Skipping lazygit symlink on non-Linux OS"; \
    fi

# Set up zsh symlink
zsh:
    @echo "Setting up zsh symlink..."
    ln -sfn {{justfile_directory()}}/zsh/.zshrc ~/.zshrc
    ln -sfn {{justfile_directory()}}/zsh/.zsh_script ~/.zsh_script
    @echo ".zshrc symlink created at ~/.zshrc -> {{justfile_directory()}}/zsh/.zshrc"
    @echo ".zsh_script symlink created at ~/.zsh_script -> {{justfile_directory()}}/zsh/.zsh_script"
    @if [ "$(uname)" = "Linux" ]; then \
        if command -v loginctl >/dev/null 2>&1; then \
            echo "Linux detected: Enabling systemd lingering to preserve background processes (like tmux) across SSH disconnects..."; \
            loginctl enable-linger $USER; \
            echo "Check current status by doing - loginctl show-user \$USER --property=Linger"; \
        fi \
    fi

# Set up SSH shared config symlink
ssh:
    @echo "Setting up SSH shared VM config symlink..."
    mkdir -p ~/.ssh
    ln -sfn {{justfile_directory()}}/ssh/config.vm.shared ~/.ssh/config.vm.shared
    @echo "SSH shared config symlink created at ~/.ssh/config.vm.shared -> {{justfile_directory()}}/ssh/config.vm.shared"


# Set up television symlink
television:
    @echo "Setting up television symlink..."
    mkdir -p ~/.config/television
    ln -sfn {{justfile_directory()}}/television/cable ~/.config/television/cable
    @echo "Television symlink created at ~/.config/television/cable -> {{justfile_directory()}}/television/cable"

# Set up all symlinks
all: nvim tmux opencode ghostty screenshot lch bin zsh lazygit television
    @echo "All dotfiles symlinked successfully!"

# Run Python tests
python-tests:
    @echo "Running Python tests using uv dev group..."
    uv run --group dev pytest


# Configure remote sshd for resilient autossh reconnects (Linux only)
# Run this on the REMOTE VM from its dotfiles checkout.
setup-ssh-forwarding:
    @if [ "$(uname)" = "Linux" ]; then \
        CONFIG_DIR="/etc/ssh/sshd_config.d"; \
        CONFIG_FILE="$CONFIG_DIR/05-vm-resilience.conf"; \
        echo "Writing SSH resilience config to $CONFIG_FILE..."; \
        sudo mkdir -p "$CONFIG_DIR"; \
        printf '%s\n' \
            '# Managed by: just setup-ssh-forwarding' \
            '# Purpose: make sleep/wake autossh reconnects fast and predictable.' \
            '' \
            '# Remove stale Unix domain socket forwards cleanly.' \
            'StreamLocalBindUnlink yes' \
            '' \
            '# Server-side keepalive: detect dead laptop clients quickly.' \
            '# 15s * 3 misses = 45s until ghost connections are dropped.' \
            'ClientAliveInterval 15' \
            'ClientAliveCountMax 3' \
            | sudo tee "$CONFIG_FILE" > /dev/null; \
        echo "Validating sshd config..."; \
        if sudo sshd -t 2>/dev/null || sudo /usr/sbin/sshd -t 2>/dev/null; then \
            echo "Config valid. Restarting sshd..."; \
            if sudo systemctl restart ssh 2>/dev/null; then \
                true; \
            elif sudo systemctl restart sshd 2>/dev/null; then \
                true; \
            else \
                echo "ERROR: Could not restart ssh.service or sshd.service."; \
                exit 1; \
            fi; \
            echo "Applied. Active values:"; \
            EFFECTIVE_VALUES="$(sudo sshd -T 2>/dev/null || sudo /usr/sbin/sshd -T 2>/dev/null)"; \
            printf '%s\n' "$EFFECTIVE_VALUES" | grep -E '^(streamlocalbindunlink|clientaliveinterval|clientalivecountmax) '; \
            EFFECTIVE_INTERVAL="$(printf '%s\n' "$EFFECTIVE_VALUES" | grep -E '^clientaliveinterval ' | cut -d' ' -f2)"; \
            EFFECTIVE_COUNTMAX="$(printf '%s\n' "$EFFECTIVE_VALUES" | grep -E '^clientalivecountmax ' | cut -d' ' -f2)"; \
            EFFECTIVE_UNLINK="$(printf '%s\n' "$EFFECTIVE_VALUES" | grep -E '^streamlocalbindunlink ' | cut -d' ' -f2)"; \
            if [ "$EFFECTIVE_INTERVAL" != "15" ] || [ "$EFFECTIVE_COUNTMAX" != "3" ] || [ "$EFFECTIVE_UNLINK" != "yes" ]; then \
                echo "WARNING: Effective sshd values differ from desired settings."; \
                echo "Desired: clientaliveinterval=15 clientalivecountmax=3 streamlocalbindunlink=yes"; \
                echo "Effective: clientaliveinterval=$EFFECTIVE_INTERVAL clientalivecountmax=$EFFECTIVE_COUNTMAX streamlocalbindunlink=$EFFECTIVE_UNLINK"; \
                echo "Hint: sshd uses first-matching values from included drop-ins. Use an earlier filename if needed."; \
            fi; \
        else \
            echo "ERROR: sshd config validation failed. Not restarting sshd."; \
            exit 1; \
        fi \
    else \
        echo "Skipping SSH forwarding setup on non-Linux OS"; \
    fi
