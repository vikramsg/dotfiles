## Config

This repo contains all settings for

1. tmux
2. NeoVim
3. Ghostty 
4. OpenCode
    - [OpenCode Github](https://github.com/anomalyco/opencode)


The settings are symlinked to their required config locations.
Prefer interacting with the settings file directly in this repo
rather than in the home directory.
Only interact with their default locations to debug if the config is not correctly setup.

## Justfile Variable Guardrail

When editing `justfile` recipes in this repo:

- Use `$VAR` for shell variable references.
- Use `$(...)` for command substitution.
- Do **not** use `$$VAR` for variable references.
- `$$` expands to the shell PID and can corrupt values/paths (for example `721854CONFIG_FILE`).
- Use `{{...}}` only for `just`-level interpolation (for example `{{justfile_directory()}}`).
