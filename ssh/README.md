# SSH + Autossh VM Workflow

This repo uses interactive SSH sessions (not background tunnel daemons) for remote development. The canonical flow is:

1. Ghostty workspace launches tabs.
2. Each tab runs `autossh` against a `vm.*` host alias.
3. SSH alias applies `LocalForward` rules and `RemoteCommand` tmux attach.
4. On laptop sleep/wake, SSH fails fast and `autossh` reconnects automatically.

---

## 1) Local Client Setup

### Ghostty workspace entrypoint

`ghostty/workspaces/vm.toml` should use `autossh` wrappers, not plain `ssh`:

```toml
command = "env AUTOSSH_POLL=30 AUTOSSH_GATETIME=0 autossh -M 0 vm.dotfiles"
```

- `AUTOSSH_POLL=30` checks child SSH health quickly (default is 600 seconds).
- `AUTOSSH_GATETIME=0` keeps retrying during Wi-Fi recovery right after lid-open.
- `-M 0` disables autossh monitor ports and relies on SSH keepalive settings.

### Shared VM SSH config

`ssh/config.vm.shared` carries all common `vm` behavior:

- `ServerAliveInterval 15`
- `ServerAliveCountMax 3`
- `ExitOnForwardFailure yes`
- All required `LocalForward` entries
- Per-host `RemoteCommand` with `tmux a -d -t <session>`

Why this matters:

- `ServerAlive*` forces dead sessions to exit quickly after sleep/wake.
- `ExitOnForwardFailure` prevents a half-broken reconnect where shell is up but forwards failed.
- `tmux a -d` detaches ghost clients left by stale TCP sessions.

---

## 2) Remote VM SSHD Setup (Required)

Client-side settings alone are not enough. The remote VM can still hold stale sessions/ports unless sshd drops inactive clients promptly.

Run this on the remote Linux VM from that machine's dotfiles checkout:

```bash
just setup-ssh-forwarding
```

What the command does:

- writes `/etc/ssh/sshd_config.d/99-vm-resilience.conf`
- sets:
  - `StreamLocalBindUnlink yes`
  - `ClientAliveInterval 15`
  - `ClientAliveCountMax 3`
- validates sshd config before restart
- restarts `sshd` (or `ssh`) when valid

Using `sshd_config.d` keeps this idempotent and avoids appending duplicate keys to `/etc/ssh/sshd_config`.

---

## 3) One-Time Remote Systemd Requirement

If `RemoteCommand` starts or attaches tmux on modern Linux distros, enable lingering once on the remote VM:

```bash
loginctl enable-linger $USER
```

Without lingering, user services/processes may be cleaned up when SSH disconnects, which can kill tmux after network drops.

---

## 4) Quick Verification

1. Open Ghostty VM workspace and confirm all tabs attach to tmux sessions.
2. Confirm local forwards are listening (`5173`, `8080`, etc.).
3. Close laptop lid for at least 1 minute.
4. Open lid and verify tabs reconnect automatically.
5. Confirm forwarded ports are working without manual reconnect.
