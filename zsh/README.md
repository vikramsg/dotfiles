# Zsh

Run `just zsh` to link the shell and prompt configuration. If `~/.zshenv` already exists outside this repository, migrate its settings before linking it.

`.zshenv` exports `EDITOR=nvim` and `VISUAL=nvim` for interactive and non-interactive Zsh processes. Keep it POSIX-compatible and free of terminal output and interactive setup: the OS Login VM also sources it from Bash.

## Local settings

Keep machine-specific aliases and interactive shell settings in `~/.zshrc.local`. This is a regular host-local file, not a repository file or symlink. The managed `.zshrc` sources it last, so local settings can override shared defaults. `just zsh` does not create, replace, or link it.

When migrating an unmanaged `~/.zshenv`, move its interactive settings into `~/.zshrc.local` and preserve the original as a backup before running `just zsh`. The linked `.zshenv` then supplies the shared editor variables on every Zsh startup.

New interactive shells load both files automatically. To refresh an existing interactive Zsh shell without reinitializing all plugins:

```zsh
source ~/.zshenv
if [[ -f "$HOME/.zshrc.local" ]]; then
    source "$HOME/.zshrc.local"
fi
```

This refreshes that shell and its future child processes, not an already-running GUI, server, or reviewr process. Do not save an old editor buffer for `~/.zshenv` after migration; reopen it to load the managed contents.

## Herdr shortcuts

Run `herdr-dot` to attach to the `dot` session with a separate saved-machine list. The shortcut sets `XDG_STATE_HOME` to `$HOME/.local/state/herdr-session-dot` for that Herdr client only; other clients keep their existing machine list. It uses the same Herdr configuration and `dot` server.

New interactive shells load the shortcut automatically. In an existing shell, run:

```sh
alias herdr-dot='XDG_STATE_HOME="$HOME/.local/state/herdr-session-dot" herdr session attach dot'
```

On macOS, with the Herdr GUI already running, use `herdr-gpui <session>` to open another window for a local session:

```sh
herdr-gpui dot
herdr-gpui default
```

This function takes exactly one session name, not native GUI CLI subcommands. It runs the installed app bundle's `window new --session` command and leaves existing windows unchanged. Unlike `herdr-dot`, it does not isolate the saved-machine list or apply a device filter. See [separate GUI windows](../herdr/README.md#separate-windows-per-session) for the underlying command and Local sidebar filter.

New interactive shells load the function automatically. To load it in an existing shell:

```sh
source ~/.zsh_script
```

## Login shell

Use Zsh as the account's login shell so remote SSH commands, including Herdr server startup, inherit these settings. Setting Herdr's `terminal.default_shell` only selects the shell inside panes; it does not change the account's login shell.

On Linux, check and change the account shell with:

```sh
getent passwd "$USER"
chsh -s /bin/zsh
```

New SSH connections use the new shell. Existing shells and Herdr servers retain their environment. Restart a Herdr server only when it is safe to end its pane processes; detaching and reattaching does not refresh its environment.

## Google OS Login VM

Google OS Login manages the account shell outside `/etc/passwd`, so `chsh` cannot change it. A Google Workspace administrator can update the POSIX shell through the Directory API, but that account-wide change may affect other VMs.

To keep Bash as the VM account shell, run `just zsh` and add this hook to `~/.bashrc` **before** its non-interactive early return:

```sh
. "$HOME/.zshenv"
```

Bash reads `.bashrc` for SSH remote commands. The hook makes remote Herdr startup inherit the same editor exports without loading interactive Zsh plugins. This hook is host-local because `.bashrc` is not managed by this repository.

Processes launched directly by a service manager do not read `.zshenv`; set their editor environment in the service configuration if they need an editor.
