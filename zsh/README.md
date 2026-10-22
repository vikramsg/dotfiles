# Zsh

Run `just zsh` to link the shell and prompt configuration. If `~/.zshenv` already exists outside this repository, migrate its settings before linking it.

`.zshenv` exports `EDITOR=nvim` and `VISUAL=nvim` for interactive and non-interactive Zsh processes. Keep it POSIX-compatible and free of terminal output and interactive setup: the OS Login VM also sources it from Bash.

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
