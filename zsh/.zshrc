#########################################
# Setup PATH to use locally installed binaries
export PATH="$HOME/.local/bin:$PATH"
if [[ -d /opt/homebrew/opt/rustup/bin ]]; then
    export PATH="/opt/homebrew/opt/rustup/bin:$PATH"
fi
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    export PATH="$HOME/.local/bin:/home/linuxbrew/.linuxbrew/bin:$PATH"
fi

#########################################
# Environment variables
export EDITOR="nvim"
export VISUAL="nvim"
# Default options for yazi. Opens preview on right and uses Tokyo Night
export FZF_DEFAULT_OPTS="--style full \
--color='fg:#c0caf5,bg:#1a1b26,hl:#ff9e64,fg+:#c0caf5,bg+:#292e42,hl+:#ff9e64,info:#7dcfff,prompt:#7aa2f7,pointer:#9ece6a,marker:#9ece6a,spinner:#bb9af7,header:#565f89,border:#3b4261,label:#bb9af7,query:#c0caf5' \
--preview 'fzf-preview.sh {}' \
--bind 'focus:transform-header:file --brief {}'"

if [[ ${HERDR_START_YAZI:-} == 1 ]]; then
    unset HERDR_START_YAZI
    exec yazi
fi

##################################################################################
# The settings above are ones we need for fast setup
# For example when opening a tab in herdr for Yazi we need some minimal setup
##################################################################################
# Install zinit
# Home is $HOME/.local/share/zinit/
# Directly copied from https://github.com/zdharma-continuum/zinit
ZINIT_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}/zinit/zinit.git"
[ ! -d $ZINIT_HOME ] && mkdir -p "$(dirname $ZINIT_HOME)"
[ ! -d $ZINIT_HOME/.git ] && git clone https://github.com/zdharma-continuum/zinit.git "$ZINIT_HOME"
source "${ZINIT_HOME}/zinit.zsh"

#########################################
# Plugins

## Prompt
### Starship

#### The following will install and then use starship. No need to install separately
#### To configure use `starship config`

#### Load starship theme
#### line 1: `starship` binary as command, from github release
#### line 2: starship setup at clone(create init.zsh, completion)
#### line 3: pull behavior same as clone, source init.zsh
zinit ice as"command" from"gh-r" \
          atclone"./starship init zsh > init.zsh; ./starship completions zsh > _starship" \
          atpull"%atclone" src"init.zsh"
zinit light starship/starship

### Syntax highlighting

#### Plugin history-search-multi-word loaded with investigating.
zinit ice wait lucid
zinit load zdharma-continuum/history-search-multi-word

#### More plugins
zinit ice wait lucid
zinit light zsh-users/zsh-completions

zinit ice wait lucid
zinit light zsh-users/zsh-autosuggestions

zinit ice wait lucid
zinit light zdharma-continuum/fast-syntax-highlighting

#### Dotenv plugin for automatic .env loading
# Disable confirmation prompt and auto-load .env files
ZSH_DOTENV_PROMPT=false
zinit snippet OMZP::dotenv

# Enable completions
autoload -Uz compinit && compinit

# -q is for quiet; actually run all the `compdef's saved before `compinit` call
# (`compinit' declares the `compdef' function, so it cannot be used until
# `compinit' is ran; Zinit solves this via intercepting the `compdef'-calls and
# storing them for later use with `zinit cdreplay')

zinit cdreplay -q

#########################################
# History Configuration
HISTFILE="$HOME/.zsh_history"
HISTSIZE=10000               # How many lines to keep in the current session
SAVEHIST=10000               # How many lines to save in the history file
# History Options
setopt APPEND_HISTORY        # Append to the history file, don't overwrite
setopt SHARE_HISTORY         # Share history between different terminal sessions
setopt HIST_IGNORE_DUPS      # Don't record the same command twice in a row
setopt HIST_IGNORE_ALL_DUPS  # Remove older duplicate entries from history
setopt HIST_IGNORE_SPACE     # Don't record commands starting with a space
setopt HIST_REDUCE_BLANKS    # Remove extra blanks from commands

#########################################
# Common aliases
alias vi="nvim"

[[ -f ~/.zsh_script ]] && source ~/.zsh_script

# Replace standard ls with eza (icons + grid view)
alias ls='eza --icons --grid'

if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    export BROWSER="xdg-open"
    export GH_BROWSER="xdg-open"
fi

# alias python="echo 'Do not use python\nUse uv for all Python related usage.'"
# alias python3="echo 'Do not use python3\nUse uv for all Python related usage.'"

#########################################
# gcloud commands
alias gcloud-auth="gcloud auth login"
alias gs="gcloud storage"

#########################################
# Init zoxide
eval "$(zoxide init zsh)"

#########################################

[[ -f ~/.zshenv ]] && source ~/.zshenv
