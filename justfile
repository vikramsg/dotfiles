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
    ln -sfn {{justfile_directory()}}/opencode/commands ~/.config/opencode/commands
    @echo "Opencode symlink created at ~/.config/opencode/opencode.json -> {{justfile_directory()}}/opencode/opencode.json"
    @echo "Opencode agent directory symlinked to ~/.config/opencode/agents"
    @echo "Opencode commands directory symlinked to ~/.config/opencode/commands"


# Set up Ghostty symlink
ghostty:
    @echo "Setting up Ghostty symlink..."
    mkdir -p ~/.config/ghostty
    ln -sfn {{justfile_directory()}}/ghostty/config ~/.config/ghostty/config
    ln -sfn {{justfile_directory()}}/ghostty/workspaces ~/.config/ghostty/workspaces
    @echo "Ghostty symlink created at ~/.config/ghostty/config -> {{justfile_directory()}}/ghostty/config"
    @echo "Ghostty workspaces symlink created at ~/.config/ghostty/workspaces -> {{justfile_directory()}}/ghostty/workspaces"


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

# Configure remote sshd for resilient autossh reconnects (Linux only)
# Run this on the REMOTE VM from its dotfiles checkout.
setup-ssh-forwarding:
    @if [ "$(uname)" = "Linux" ]; then \
        CONFIG_DIR="/etc/ssh/sshd_config.d"; \
        CONFIG_FILE="$$CONFIG_DIR/99-vm-resilience.conf"; \
        echo "Writing SSH resilience config to $$CONFIG_FILE..."; \
        sudo mkdir -p "$$CONFIG_DIR"; \
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
            | sudo tee "$$CONFIG_FILE" > /dev/null; \
        echo "Validating sshd config..."; \
        if sudo sshd -t 2>/dev/null || sudo /usr/sbin/sshd -t 2>/dev/null; then \
            echo "Config valid. Restarting sshd..."; \
            sudo systemctl restart sshd || sudo systemctl restart ssh; \
            echo "Applied. Active values:"; \
            sudo sshd -T 2>/dev/null | grep -E 'streamlocalbindunlink|clientaliveinterval|clientalivecountmax' \
                || sudo /usr/sbin/sshd -T 2>/dev/null | grep -E 'streamlocalbindunlink|clientaliveinterval|clientalivecountmax'; \
        else \
            echo "ERROR: sshd config validation failed. Not restarting sshd."; \
            exit 1; \
        fi \
    else \
        echo "Skipping SSH forwarding setup on non-Linux OS"; \
    fi

# Set up all symlinks
all: nvim tmux opencode ghostty bin zsh lazygit
    @echo "All dotfiles symlinked successfully!"

# Run Python tests
python-tests:
    @echo "Running Python tests using uv dev group..."
    uv run --group dev pytest

# Install CLI tools
install-tools:
    @echo "Installing eza, zoxide, and chafa..."
    @if ! command -v brew > /dev/null; then \
        echo "Homebrew is not installed. Please install Homebrew first."; \
        exit 1; \
    fi
    brew install eza zoxide chafa
    @echo "The following tools have been successfully installed:"
    @echo "  - eza"
    @echo "  - zoxide"
    @echo "  - chafa"
