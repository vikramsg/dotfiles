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
# Mise shims make pinned tools available to SSH commands and non-interactive shells.
export PATH="${MISE_DATA_DIR:-$HOME/.local/share/mise}/shims:$PATH"

# Ziggity has no global config path of its own; see ziggity/config.ini.
export ZIGGITY_CONFIG="$HOME/.config/ziggity/config.ini"

export EDITOR="nvim"
export VISUAL="nvim"

# `herdr_profile work` opens the Herdr app as a separate profile: its own window, settings and
# layouts (app home ~/.config/herdr-app-work) and its own herdr-core session (HC_SESSION=work),
# so its spaces and terminals are apart from the default window's. Running it again brings that
# profile's window to the front. A new profile starts with Herdr's default settings and keys.
if [ -d /Applications/Herdr.app ]; then
    herdr_profile() {
        if [ -z "$1" ]; then
            echo "usage: herdr_profile <name>" >&2
            return 2
        fi
        open -n -a /Applications/Herdr.app --env HERDR_APP_HOME="$HOME/.config/herdr-app-$1" --env HC_SESSION="$1"
    }
fi
