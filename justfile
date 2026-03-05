# List available commands
default:
    @just --list

# Set up Neovim symlink
nvim:
    @echo "Setting up Neovim symlink..."
    mkdir -p ~/.config
    ln -sfn {{justfile_directory()}}/nvim ~/.config/nvim
    @echo "Neovim symlink created at ~/.config/nvim -> {{justfile_directory()}}/nvim"
    @if ! command -v mdr &> /dev/null; then \
        echo "Installing mdr via Homebrew for markdown previews..."; \
        brew tap CleverCloud/misc; \
        brew install mdr; \
    else \
        echo "mdr is already installed."; \
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
    @if ! command -v gitmux &> /dev/null; then \
        echo "Installing gitmux via Homebrew..."; \
        brew install gitmux; \
    else \
        echo "gitmux is already installed."; \
    fi

# Set up Opencode symlink
opencode:
    @echo "Setting up Opencode symlink..."
    mkdir -p ~/.config
    mkdir -p ~/.config/opencode
    ln -sfn {{justfile_directory()}}/opencode/opencode.json ~/.config/opencode/opencode.json
    ln -sfn {{justfile_directory()}}/opencode/agents ~/.config/opencode/agents
    @echo "Opencode symlink created at ~/.config/opencode/opencode.json -> {{justfile_directory()}}/opencode/opencode.json"
    @echo "Opencode agent directory symlinked to ~/.config/opencode/agents"


# Set up Ghostty symlink
ghostty:
    @echo "Setting up Ghostty symlink..."
    mkdir -p ~/.config/ghostty
    ln -sfn {{justfile_directory()}}/ghostty/config ~/.config/ghostty/config
    @echo "Ghostty symlink created at ~/.config/ghostty/config -> {{justfile_directory()}}/ghostty/config"


# Set up custom bin symlinks
bin:
    @echo "Setting up custom bin symlinks..."
    mkdir -p ~/.local/bin
    ln -sfn {{justfile_directory()}}/bin/lc ~/.local/bin/lc
    @if [ "$(uname)" = "Linux" ]; then \
        ln -sfn {{justfile_directory()}}/bin/xdg-open ~/.local/bin/xdg-open; \
        echo "xdg-open symlink created at ~/.local/bin/xdg-open"; \
    fi

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
    @echo ".zshrc symlink created at ~/.zshrc -> {{justfile_directory()}}/zsh/.zshrc"

# Set up SSH remote forwarding socket fix (Linux only)
setup-ssh-forwarding:
    @if [ "$(uname)" = "Linux" ]; then \
        echo "Setting up SSH StreamLocalBindUnlink fix..."; \
        if ! grep -q "^StreamLocalBindUnlink yes" /etc/ssh/sshd_config; then \
            echo "StreamLocalBindUnlink yes" | sudo tee -a /etc/ssh/sshd_config > /dev/null; \
            echo "Restarting sshd..."; \
            sudo systemctl restart sshd || sudo systemctl restart ssh; \
            echo "SSH socket fix applied successfully."; \
        else \
            echo "StreamLocalBindUnlink is already enabled in /etc/ssh/sshd_config."; \
        fi \
    else \
        echo "Skipping SSH socket fix on non-Linux OS"; \
    fi

# Set up all symlinks
all: nvim tmux opencode ghostty bin zsh lazygit
    @echo "All dotfiles symlinked successfully!"

# Install and manage screenshot sync tool
screenshot-sync-install:
    @echo "Installing screenshot-sync tool via uv workspace..."
    # --force: Reinstalls even if already present.
    # --no-cache: Bypasses cache to ensure local code changes are applied.
    uv tool install {{justfile_directory()}}/bin/screenshot_sync --force --no-cache
    @echo "Tool installed to ~/.local/bin/screenshot-sync"


# Manage screenshot sync launchd agent (install, uninstall, status, logs, debug, help)
screenshot-sync-launchd action="help":
    @if [ ! -f ~/.local/bin/screenshot-sync ]; then \
        echo "Error: Tool not installed. Please run 'just screenshot-sync-install' first."; \
        exit 1; \
    fi
    ~/.local/bin/screenshot-sync launchd {{action}}

# Run Python tests
python-tests:
    @echo "Running Python tests using uv dev group..."
    uv run --group dev pytest


