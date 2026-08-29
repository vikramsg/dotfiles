# NOTE: Guardrail for just recipes in this repo:
# - Use $VAR for shell variable references.
# - Use $(...) for command substitution.
# - Do NOT use $$VAR for variable references.
# - $$ expands to shell PID and can corrupt paths (for example 721854CONFIG_FILE).
# - Use {{...}} only for just-level interpolation.

set positional-arguments := true

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

# Configure npm global installs to place binaries in ~/.local/bin
npm-global-bin:
    @echo "Configuring npm global binary directory..."
    mkdir -p ~/.local/bin
    NPM_CONFIG_PREFIX="$HOME/.local" npm config set prefix "$HOME/.local"
    @PREFIX="$(NPM_CONFIG_PREFIX="$HOME/.local" npm config get prefix)"; \
        EXPECTED_PREFIX="$HOME/.local"; \
        if [ "$PREFIX" != "$EXPECTED_PREFIX" ]; then \
            echo "ERROR: npm prefix is $PREFIX, expected $EXPECTED_PREFIX"; \
            exit 1; \
        fi
    @echo "npm global binaries will install to ~/.local/bin"

# Set up Neovim symlink
nvim:
    @echo "Setting up Neovim symlink..."
    mkdir -p ~/.config
    ln -sfn {{justfile_directory()}}/nvim ~/.config/nvim
    @echo "Neovim symlink created at ~/.config/nvim -> {{justfile_directory()}}/nvim"

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

# Set up Yazi config symlink
yazi:
    @echo "Setting up Yazi config symlink..."
    mkdir -p ~/.config/yazi
    mkdir -p ~/.config/yazi/profiles/screenshots
    ln -sfn {{justfile_directory()}}/yazi/yazi.toml ~/.config/yazi/yazi.toml
    ln -sfn {{justfile_directory()}}/yazi/keymap.toml ~/.config/yazi/keymap.toml
    ln -sfn {{justfile_directory()}}/yazi/profiles/screenshots/yazi.toml ~/.config/yazi/profiles/screenshots/yazi.toml
    @echo "Yazi config symlink created at ~/.config/yazi/yazi.toml -> {{justfile_directory()}}/yazi/yazi.toml"
    @echo "Yazi keymap symlink created at ~/.config/yazi/keymap.toml -> {{justfile_directory()}}/yazi/keymap.toml"
    @echo "Yazi Screenshots config symlink created at ~/.config/yazi/profiles/screenshots/yazi.toml -> {{justfile_directory()}}/yazi/profiles/screenshots/yazi.toml"

# Set up Herdr config symlink while preserving its runtime directory
herdr:
    @CONFIG_FILE="{{justfile_directory()}}/herdr/config.toml"; \
        CONFIG_DIR="$HOME/.config/herdr"; \
        TARGET="$CONFIG_DIR/config.toml"; \
        echo "Herdr config source: $CONFIG_FILE"; \
        echo "Herdr config target: $TARGET"; \
        mkdir -p "$HOME/.config"; \
        if [ -L "$CONFIG_DIR" ]; then \
            echo "ERROR: $CONFIG_DIR is a symlink; Herdr requires a normal runtime directory."; \
            exit 1; \
        elif [ -e "$CONFIG_DIR" ] && [ ! -d "$CONFIG_DIR" ]; then \
            echo "ERROR: $CONFIG_DIR exists and is not a directory."; \
            exit 1; \
        fi; \
        mkdir -p "$CONFIG_DIR"; \
        if [ -L "$TARGET" ]; then \
            CURRENT_TARGET="$(readlink "$TARGET")"; \
            if [ "$CURRENT_TARGET" != "$CONFIG_FILE" ]; then \
                echo "ERROR: $TARGET is a symlink to $CURRENT_TARGET, not the managed config."; \
                exit 1; \
            fi; \
        elif [ -e "$TARGET" ]; then \
            echo "ERROR: $TARGET exists and is not the managed symlink."; \
            echo "Move or migrate it manually before running this recipe."; \
            exit 1; \
        else \
            ln -s "$CONFIG_FILE" "$TARGET"; \
        fi; \
        echo "Herdr config symlink created at $TARGET -> $CONFIG_FILE"

# Set up tuicr config symlink
tuicr:
    @echo "Setting up tuicr config symlink..."
    mkdir -p ~/.config/tuicr
    ln -sfn {{justfile_directory()}}/tuicr/config.toml ~/.config/tuicr/config.toml
    @echo "tuicr config symlink created at ~/.config/tuicr/config.toml -> {{justfile_directory()}}/tuicr/config.toml"

# Set up Opencode symlink
opencode: npm-global-bin
    @echo "Setting up Opencode symlink..."
    @if [ ! -x "$HOME/.local/bin/opencode" ]; then \
        echo "OpenCode not found. Installing with npm..."; \
        NPM_CONFIG_PREFIX="$HOME/.local" npm i -g opencode-ai; \
    fi
    mkdir -p ~/.config
    mkdir -p ~/.config/opencode
    mkdir -p ~/.config/opencode/skills
    ln -sfn {{justfile_directory()}}/opencode/opencode.json ~/.config/opencode/opencode.json
    ln -sfn {{justfile_directory()}}/opencode/tui.json ~/.config/opencode/tui.json
    ln -sfn {{justfile_directory()}}/opencode/cli.json ~/.config/opencode/cli.json
    ln -sfn {{justfile_directory()}}/opencode/rules.md ~/.config/opencode/rules.md
    ln -sfn {{justfile_directory()}}/opencode/AGENTS.md ~/.config/opencode/AGENTS.md
    ln -sfn {{justfile_directory()}}/opencode/agents ~/.config/opencode/agents
    ln -sfn {{justfile_directory()}}/opencode/commands ~/.config/opencode/commands
    ln -sfn {{justfile_directory()}}/opencode/prompts ~/.config/opencode/prompts
    ln -sfn {{justfile_directory()}}/skills/show-me ~/.config/opencode/skills/show-me
    ln -sfn {{justfile_directory()}}/skills/herdr ~/.config/opencode/skills/herdr
    ln -sfn {{justfile_directory()}}/skills/hunk-review ~/.config/opencode/skills/hunk-review
    @if [  -d {{justfile_directory()}}/opencode/plugins ]; then ln -sfn {{justfile_directory()}}/opencode/plugins ~/.config/opencode/plugins; \
    fi
    @echo "Opencode symlink created at ~/.config/opencode/opencode.json -> {{justfile_directory()}}/opencode/opencode.json"
    @echo "OpenCode 2 CLI config symlinked to ~/.config/opencode/cli.json"
    @echo "Opencode rules file symlinked to ~/.config/opencode/rules.md"
    @echo "OpenCode instructions symlinked to ~/.config/opencode/AGENTS.md"
    @echo "Opencode agent directory symlinked to ~/.config/opencode/agents"
    @echo "Opencode commands directory symlinked to ~/.config/opencode/commands"
    @echo "OpenCode show-me skill symlinked to ~/.config/opencode/skills/show-me"
    @echo "OpenCode Herdr skill symlinked to ~/.config/opencode/skills/herdr"
    @echo "OpenCode Hunk review skill symlinked to ~/.config/opencode/skills/hunk-review"
    @echo "Opencode plugins directory symlinked to ~/.config/opencode/plugins"
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

# Run OpenCode sandbox CLI
opencode-sandbox +args:
    @npm --prefix "{{justfile_directory()}}/opencode" run --silent sandbox -- "$@"

# Install the read-only OpenCode SQLite intelligence tool
ocint:
    uv tool install "{{justfile_directory()}}/bin/ocint" --force --no-cache

# Install GitHub pull request statistics tool
gh-stats:
    uv tool install "{{justfile_directory()}}/bin/gh_stats" --force --no-cache

# Set up Ghostty symlink
ghostty:
    @echo "Setting up Ghostty symlink..."
    mkdir -p ~/.config/ghostty
    ln -sfn {{justfile_directory()}}/ghostty/config ~/.config/ghostty/config
    ln -sfn {{justfile_directory()}}/ghostty/workspaces ~/.config/ghostty/workspaces
    @echo "Ghostty symlink created at ~/.config/ghostty/config -> {{justfile_directory()}}/ghostty/config"
    @echo "Ghostty workspaces symlink created at ~/.config/ghostty/workspaces -> {{justfile_directory()}}/ghostty/workspaces"


# Set up Zed symlink
zed:
    @echo "Setting up Zed symlink..."
    mkdir -p ~/.config/zed
    ln -sfn {{justfile_directory()}}/zed/settings.json ~/.config/zed/settings.json
    ln -sfn {{justfile_directory()}}/zed/keymap.json ~/.config/zed/keymap.json
    @echo "Zed settings symlink created at ~/.config/zed/settings.json -> {{justfile_directory()}}/zed/settings.json"
    @echo "Zed keymap symlink created at ~/.config/zed/keymap.json -> {{justfile_directory()}}/zed/keymap.json"

# Install ZWM locally and, from macOS, on the configured VM.
zwm:
    @SOURCE="{{justfile_directory()}}/zwm/config.json"; \
    TARGET="$HOME/.config/zwm/config.json"; \
    mkdir -p "$HOME/.config/zwm"; \
    if [ -L "$TARGET" ] && [ "$(readlink "$TARGET")" = "$SOURCE" ]; then \
        :; \
    elif [ -e "$TARGET" ] && [ ! -L "$TARGET" ]; then \
        echo "ERROR: $TARGET exists and is not a symlink."; \
        exit 1; \
    else \
        TEMP_DIR="$(mktemp -d "$HOME/.config/zwm/.link.XXXXXX")"; \
        trap 'rm -f "$TEMP_DIR/config.json"; rmdir "$TEMP_DIR" 2>/dev/null || true' EXIT; \
        ln -s "$SOURCE" "$TEMP_DIR/config.json"; \
        mv -f "$TEMP_DIR/config.json" "$TARGET"; \
    fi
    just --justfile "{{justfile_directory()}}/bin/zwm/justfile" install


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
    ln -sfn {{justfile_directory()}}/lch/config.toml ~/.config/lch/config.toml
    uv tool install ./bin/lch --force --no-cache
    @if [ "$(uname)" = "Darwin" ]; then \
        SCREENSHOT="$HOME/.local/bin/screenshot"; \
        LCH="$HOME/.local/bin/lch"; \
        for source_id in $("$SCREENSHOT" sync list); do \
            watch_path=$("$SCREENSHOT" sync watch-path "$source_id"); \
            "$LCH" install-watcher \
                "lch-screenshot-sync-$source_id" \
                "$watch_path" \
                "$SCREENSHOT" sync run "$source_id"; \
        done; \
        "$HOME/.local/bin/lch" install lch-zwm; \
    elif [ "$(uname)" = "Linux" ]; then \
        "$HOME/.local/bin/lch" install lch-screenshot-clipboard; \
    fi
    @echo "lch config symlink created at ~/.config/lch/config.toml -> {{justfile_directory()}}/lch/config.toml"

# Install the browser-opener binary and its config without reinstalling LCH.
[private]
opener-tunnel-install:
    @if [ "$(uname)" != "Darwin" ]; then \
        echo "ERROR: opener-tunnel setup requires macOS."; \
        exit 1; \
    fi; \
    mkdir -p "$HOME/.config/opener-tunnel"; \
    ln -sfn "{{justfile_directory()}}/opener_tunnel/config.toml" "$HOME/.config/opener-tunnel/config.toml"; \
    uv tool install "{{justfile_directory()}}/bin/opener_tunnel" --force --no-cache; \
    "$HOME/.local/bin/lch" install lch-opener-tunnel

# Install the config-driven macOS browser-opener service.
opener-tunnel: lch opener-tunnel-install

# Install the browser-opener service from `all` only on supported hosts.
[private]
opener-tunnel-if-supported:
    @if [ "$(uname)" = "Darwin" ]; then \
        just --justfile "{{justfile()}}" opener-tunnel-install; \
    else \
        echo "Skipping opener-tunnel: setup requires macOS."; \
    fi


# Set up custom bin symlinks
bin:
    @echo "Setting up custom bin symlinks..."
    mkdir -p ~/.local/bin
    ln -sfn {{justfile_directory()}}/bin/lc ~/.local/bin/lc
    ln -sfn {{justfile_directory()}}/bin/xdg-open ~/.local/bin/xdg-open
    @echo "bin symlinks created at ~/.local/bin"

# Set up lazygit symlink
lazygit:
    @echo "Setting up lazygit symlinks..."; \
    mkdir -p ~/.config/lazygit; \
    ln -sfn {{justfile_directory()}}/lazygit/config.yml ~/.config/lazygit/config.yml; \
    echo "lazygit symlink created at ~/.config/lazygit/config.yml"; \
    if [ "$(uname)" = "Darwin" ]; then \
        mkdir -p "$HOME/Library/Application Support/lazygit"; \
        ln -sfn {{justfile_directory()}}/lazygit/config.yml "$HOME/Library/Application Support/lazygit/config.yml"; \
        echo "lazygit symlink created at ~/Library/Application Support/lazygit/config.yml"; \
    fi

# Set up Hunk config and extensions symlink
hunk:
    @echo "Setting up Hunk config and extension symlinks..."
    mkdir -p ~/.config/hunk
    ln -sfn {{justfile_directory()}}/hunk/config.toml ~/.config/hunk/config.toml
    @if [ -d {{justfile_directory()}}/hunk/extensions ]; then \
        ln -sfn {{justfile_directory()}}/hunk/extensions ~/.config/hunk/extensions; \
    fi
    @echo "Hunk config symlinked to ~/.config/hunk"

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

# Set up Git config symlink without storing identity in the repo
git:
    @echo "Setting up Git config symlink..."
    mkdir -p ~/.config/git
    @CONFIG_FILE="{{justfile_directory()}}/git/config"; \
        TARGET="$HOME/.gitconfig"; \
        IDENTITY_FILE="$HOME/.config/git/identity.local"; \
        if [ -L "$TARGET" ]; then \
            CURRENT_TARGET="$(readlink "$TARGET")"; \
            if [ "$CURRENT_TARGET" != "$CONFIG_FILE" ]; then \
                echo "ERROR: $TARGET is a symlink to $CURRENT_TARGET"; \
                echo "Update it manually before running this recipe."; \
                exit 1; \
            fi; \
        elif [ -e "$TARGET" ]; then \
            echo "ERROR: $TARGET exists and is not the managed symlink."; \
            echo "Move private identity values to $IDENTITY_FILE, then replace $TARGET with a symlink to $CONFIG_FILE."; \
            exit 1; \
        fi; \
        ln -sfn "$CONFIG_FILE" "$TARGET"; \
        echo "Git config symlink created at $TARGET -> $CONFIG_FILE"; \
        if [ ! -f "$IDENTITY_FILE" ]; then \
            echo "WARNING: Missing private Git identity file at $IDENTITY_FILE"; \
            echo "Create it from {{justfile_directory()}}/git/identity.local.example without committing it."; \
        fi

# Verify Git config symlink and non-PII behavior
git-doctor:
    @CONFIG_FILE="{{justfile_directory()}}/git/config"; \
        TARGET="$HOME/.gitconfig"; \
        IDENTITY_FILE="$HOME/.config/git/identity.local"; \
        if [ ! -L "$TARGET" ]; then \
            echo "ERROR: $TARGET is not a symlink."; \
            exit 1; \
        fi; \
        CURRENT_TARGET="$(readlink "$TARGET")"; \
        if [ "$CURRENT_TARGET" != "$CONFIG_FILE" ]; then \
            echo "ERROR: $TARGET points to $CURRENT_TARGET"; \
            echo "Expected: $CONFIG_FILE"; \
            exit 1; \
        fi; \
        PUSH_DEFAULT="$(git config --global --get push.default || true)"; \
        AUTO_SETUP_MERGE="$(git config --global --get branch.autoSetupMerge || true)"; \
        if [ "$PUSH_DEFAULT" != "current" ]; then \
            echo "ERROR: Expected push.default=current, got '$PUSH_DEFAULT'"; \
            exit 1; \
        fi; \
        if [ "$AUTO_SETUP_MERGE" != "simple" ]; then \
            echo "ERROR: Expected branch.autoSetupMerge=simple, got '$AUTO_SETUP_MERGE'"; \
            exit 1; \
        fi; \
        if [ ! -f "$IDENTITY_FILE" ]; then \
            echo "ERROR: Missing private Git identity file at $IDENTITY_FILE"; \
            exit 1; \
        fi; \
        if ! git config --global --get user.name > /dev/null; then \
            echo "ERROR: Git user.name is not configured."; \
            exit 1; \
        fi; \
        if ! git config --global --get user.email > /dev/null; then \
            echo "ERROR: Git user.email is not configured."; \
            exit 1; \
        fi; \
        echo "Git config symlink is correct."; \
        echo "Git push.default and branch.autoSetupMerge are correct."; \
        echo "Git identity resolves without printing PII."


# Set up television symlink
television:
    @echo "Setting up television symlink..."
    mkdir -p ~/.config/television
    ln -sfn {{justfile_directory()}}/television/cable ~/.config/television/cable
    @echo "Television symlink created at ~/.config/television/cable -> {{justfile_directory()}}/television/cable"

# Set up Harlequin symlink
harlequin:
    @echo "Setting up Harlequin symlink..."
    mkdir -p ~/.config/harlequin
    @if [ ! -f {{justfile_directory()}}/harlequin/config.toml ]; then \
        echo "Missing local Harlequin config: {{justfile_directory()}}/harlequin/config.toml"; \
        echo "Create it from harlequin/config.example.toml and fill in local credentials."; \
        exit 1; \
    fi
    ln -sfn {{justfile_directory()}}/harlequin/config.toml ~/.config/harlequin/config.toml
    @echo "Harlequin symlink created at ~/.config/harlequin/config.toml -> {{justfile_directory()}}/harlequin/config.toml"

# Keep `all` usable when the intentionally untracked local credentials are absent.
[private]
harlequin-if-configured:
    @if [ -f "{{justfile_directory()}}/harlequin/config.toml" ]; then \
        just --justfile "{{justfile()}}" harlequin; \
    else \
        echo "Skipping Harlequin: create harlequin/config.toml from config.example.toml to enable it."; \
    fi

# Install or update terminal-browser
# Installs binary to ~/.local/bin/terminal-browser (already exported in ~/.zshrc)
# the installation also links the agent skill into ~/.agents/skills for automatic OpenCode/agent discovery.
terminal-browser:
    @echo "Installing terminal-browser..."
    @curl -fsSL https://terminal-browser.sh/install | bash

# Set up all symlinks
all: npm-global-bin nvim tmux yazi herdr tuicr opencode ghostty zed screenshot zwm lch opener-tunnel-if-supported ocint gh-stats bin zsh lazygit hunk television harlequin-if-configured
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
