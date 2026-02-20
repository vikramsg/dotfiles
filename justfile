# List available commands
default:
    @just --list

# Set up Neovim symlink
nvim:
    @echo "Setting up Neovim symlink..."
    mkdir -p ~/.config
    ln -sfn {{justfile_directory()}}/nvim ~/.config/nvim
    @echo "Neovim symlink created at ~/.config/nvim -> {{justfile_directory()}}/nvim"

# Set up Tmux symlink
tmux:
    @echo "Setting up Tmux symlink..."
    ln -sf {{justfile_directory()}}/tmux/.tmux.conf ~/.tmux.conf
    @echo "Tmux symlink created at ~/.tmux.conf -> {{justfile_directory()}}/tmux/.tmux.conf"
    @echo "Installing Tmux Plugin Manager (TPM)..."
    @if [ ! -d ~/.tmux/plugins/tpm ]; then git clone https://github.com/tmux-plugins/tpm ~/.tmux/plugins/tpm; else echo "TPM is already installed."; fi

# Set up all symlinks
all: nvim tmux
    @echo "All dotfiles symlinked successfully!"
