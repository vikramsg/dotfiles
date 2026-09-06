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

## Custom Tool Layout

- Keep each custom tool's implementation, package-local build definition and `justfile`, tests, and implementation docs in `bin/<tool>/`.
- Keep user-editable configuration and user-facing configuration docs in `<tool>/` at the repository root.
- Declare persistent service lifecycle in `lch/config.toml`.
- Keep the root `justfile` limited to linking tool configuration and delegating build and installation to `bin/<tool>/justfile`.

## Testing

###  Avoid change-detection tests

- Do not add tests that merely assert that recently changed text, labels, or presentation elements are present or absent. 
- Test meaningful behavior and invariants instead. For copy-only or cosmetic changes, prefer existing tests and manual verification; adding no new test is acceptable.

## Justfile Variable Guardrail

When editing `justfile` recipes in this repo:

- Use `$VAR` for shell variable references.
- Use `$(...)` for command substitution.
- Do **not** use `$$VAR` for variable references.
- `$$` expands to the shell PID and can corrupt values/paths (for example `721854CONFIG_FILE`).
- Use `{{...}}` only for `just`-level interpolation (for example `{{justfile_directory()}}`).

## Pull Request Titles

Pull request titles must use `scope: summary` with one of these explicit scopes:

- `chore`
- `ghostty`
- `git`
- `herdr`
- `lch`
- `macflow`
- `nvim`
- `ocint`
- `opencode`
- `screenshot`
- `terraform`
- `tmux`
- `zed`

The summary must be non-empty and the title must not contain leading, trailing, or multiline whitespace.

All changes, including releases, must go through a pull request. Never commit or push directly to
`main`.

## vm workflows

We use the repo local `lch` binary to launch `launchd` services on Mac and `systemd` services on Linux.
The repo is used to manage configuration on the 2 machines, local dev on Mac and remote dev on remote VM which uses Linux.
In addition we also have custom binaries managed through this repo for managing custom workflows.

### Screenshot workflow

- Configuration: `screenshot/config.json`
- Screenshot CLI and sync implementation: `bin/screenshot/`
- LCH watcher/orchestration: `bin/lch/`

```bash
Mac /Users/Shared/Screenshots
  -> lch-screenshot-sync
  -> rsync
  -> vm-us:/Users/Shared/Screenshots
  -> lch-screenshot-clipboard
  -> VM clipboard
```

`lch-screenshot-sync-system` watches screenshots on macOS. `lch-screenshot-clipboard`
watches the synchronized directory on the VM and copies the latest path to its clipboard.
Keep `/Users/Shared/Screenshots` writable on both hosts; see `screenshot/README.md` for setup.

### Browser opener tunnel

`lch-opener-tunnel` maintains the Mac-side SSH reverse socket tunnel so processes on `vm-us` can open URLs in the Mac browser. Its implementation is `bin/opener_tunnel/` and its configuration is `opener_tunnel/config.toml`.
