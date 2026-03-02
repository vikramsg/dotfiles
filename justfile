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
    @echo "Opencode symlink created at ~/.config/opencode/opencode.json -> {{justfile_directory()}}/opencode/opencode.json"


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

# Set up all symlinks
all: nvim tmux opencode ghostty bin zsh lazygit
    @echo "All dotfiles symlinked successfully!"
