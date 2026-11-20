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

# Herdr app profiles: separate windows with the main window's setup; see `herdr_profile --help`.
if [ -d /Applications/Herdr.app ]; then
    herdr_profile() {
        case "$1" in
            -h | --help | "")
                cat <<'EOF'
usage: herdr_profile <name>

Opens the Herdr app as profile <name>: a window of its own whose spaces, tabs
and terminals are apart from the main window's and other profiles'.

- Terminals run in their own herdr-core session, HC_SESSION=<name>; `hc` in
  them sees only that session.
- The window's home is ~/.config/herdr-app-<name>. It has the main window's
  setup: settings, keys, theme and mods linked from the dotfiles repo, and
  third-party mods and the main-copy layout copied from ~/.config/herdr-app.
- The first run sets the home up (`just herdr-app-profile <name>`), and
  `just herdr-app` refreshes every profile's home.
- Running it again brings that profile's window to the front.
EOF
                [ -n "$1" ]
                return ;;
        esac
        if [ ! -d "$HOME/.config/herdr-app-$1" ]; then
            local dotfiles
            dotfiles="$(dirname "$(dirname "$(readlink "$HOME/.zshenv")")")"
            just --justfile "$dotfiles/justfile" herdr-app-profile "$1" || return
        fi
        open -n -a /Applications/Herdr.app --env HERDR_APP_HOME="$HOME/.config/herdr-app-$1" --env HC_SESSION="$1"
    }
fi
