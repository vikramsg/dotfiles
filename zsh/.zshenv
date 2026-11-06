# SSH-launched daemons need these executable paths before interactive shells start.
# Keep this file POSIX-compatible: the OS Login VM also sources it from Bash.
if [ -d /home/linuxbrew/.linuxbrew/bin ]; then
    export PATH="/home/linuxbrew/.linuxbrew/bin:$PATH"
fi
# Cargo-installed tools such as uv, which Herdr plugin actions run through the server's PATH.
if [ -d "$HOME/.cargo/bin" ]; then
    export PATH="$HOME/.cargo/bin:$PATH"
fi
export PATH="$HOME/.local/bin:$PATH"

export EDITOR="nvim"
export VISUAL="nvim"
