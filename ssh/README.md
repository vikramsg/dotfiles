# SSH + Autossh VM Workflow

This repo uses interactive SSH sessions (not background tunnel daemons) for remote development.

The canonical flow is:

1. Ghostty workspace launches tabs.
2. Each tab runs `autossh` against a `vm.*` alias.
3. SSH alias applies tmux attach behavior.
4. Exactly one tab owns local forwards.
5. On sleep/wake, SSH fails fast and `autossh` reconnects.

---

## 1) SSH Config Inheritance (DRY Aliases)

SSH config matching is top-down and first-match-wins per key.

That means:

- Put specific aliases first (`vm.dotfiles`, `vm.kunda`, etc.).
- Put shared wildcard/base rules later (`vm`, `vm.*`).
- If a key is already set by a specific block, later blocks do not override it.

Example pattern:

```ssh-config
# Specific session aliases first
Host vm.dotfiles
    RemoteCommand /home/linuxbrew/.linuxbrew/bin/tmux a -d -t dotfiles

Host vm.kunda
    RemoteCommand /home/linuxbrew/.linuxbrew/bin/tmux a -d -t kunda

# Shared base rules later
Host vm vm.*
    RequestTTY yes
    ServerAliveInterval 15
    ServerAliveCountMax 3
```

This lets each alias define session behavior while still inheriting shared connection settings.

---

## 2) Connecting to VM

### Single session from terminal

- Forwarding owner session (dotfiles):

```bash
env AUTOSSH_POLL=30 AUTOSSH_GATETIME=0 autossh -M 0 vm.dotfiles
```

- Non-forwarding session (avoid port collisions):

```bash
env AUTOSSH_POLL=30 AUTOSSH_GATETIME=0 autossh -M 0 -o ClearAllForwardings=yes vm.kunda
```

### Full multi-tab workflow via Ghostty

- Launch your VM workspace.
- Keep one tab as forwarding owner (`vm.dotfiles`).
- Keep all other tabs with `ClearAllForwardings=yes`.

---

## 3) Local Client Setup

### Ghostty workspace entrypoint

`ghostty/workspaces/vm.toml` uses `autossh` wrappers, not plain `ssh`.

Forwarding-owner tab example:

```toml
command = "env AUTOSSH_POLL=30 AUTOSSH_GATETIME=0 autossh -M 0 vm.dotfiles"
```

Non-forwarding tab example:

```toml
command = "env AUTOSSH_POLL=30 AUTOSSH_GATETIME=0 autossh -M 0 -o ClearAllForwardings=yes vm.kunda"
```

- `AUTOSSH_POLL=30` checks child SSH health quickly (default is 600 seconds).
- `AUTOSSH_GATETIME=0` keeps retrying during Wi-Fi recovery right after lid-open.
- `-M 0` disables autossh monitor ports and relies on SSH keepalive settings.
- `ClearAllForwardings=yes` prevents forwarding collisions on non-owner tabs.

### Shared VM SSH config

`ssh/config.vm.shared` carries common `vm` behavior:

- `ServerAliveInterval 15`
- `ServerAliveCountMax 3`
- `ExitOnForwardFailure yes`
- Per-host `RemoteCommand` with `tmux a -d -t <session>`

Only `vm.dotfiles` owns `LocalForward` rules.

Why this matters:

- `ServerAlive*` forces dead sessions to exit quickly after sleep/wake.
- `ExitOnForwardFailure` prevents a half-broken reconnect where shell is up but forwards failed.
- `tmux a -d` detaches ghost clients left by stale TCP sessions.
- Single forwarding owner avoids `Address already in use` bind errors.

---

## 4) Remote VM SSHD Setup (Required)

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

## 5) One-Time Remote Systemd Requirement

If `RemoteCommand` starts or attaches tmux on modern Linux distros, enable lingering once on the remote VM:

```bash
loginctl enable-linger $USER
```

Without lingering, user services/processes may be cleaned up when SSH disconnects, which can kill tmux after network drops.

---

## 6) Troubleshooting

### Interpreting `lsof` for forwarded ports

Run:

```bash
lsof -nP -iTCP:5173,8080,8081,19876,54321,54323 -sTCP:LISTEN
```

What output means:

- **Good state:** one `ssh` PID owns all forwarded ports.
- Each port appears twice (`127.0.0.1` and `[::1]`) because SSH listens on IPv4 + IPv6 loopback.
- `LISTEN` means your local tunnel entrypoint is active and ready.

Example interpretation:

- `ssh 86662 ... TCP 127.0.0.1:8080 (LISTEN)` and `TCP [::1]:8080 (LISTEN)` means PID `86662` owns port `8080` correctly.

If multiple different `ssh`/`autossh` PIDs own the same forward set, expect collisions.

### `Address already in use` on local forward ports

If you see errors like:

`bind [127.0.0.1]:8080: Address already in use`

it means more than one SSH/autossh session is trying to bind the same local ports.

Fix:

1. Keep forwards on one alias only (`vm.dotfiles`).
2. Use `-o ClearAllForwardings=yes` for all other tabs.
3. Close stale local SSH sessions that already own those ports.

### Reconnect happened but tmux sizing/session looks wrong

Use `tmux a -d -t <session>` in `RemoteCommand` so stale clients are detached on reconnect.

---

## 7) Quick Verification

1. Open Ghostty VM workspace and confirm all tabs attach to tmux sessions.
2. Confirm only one session is listening on forwarded local ports.
3. Close laptop lid for at least 1 minute.
4. Open lid and verify tabs reconnect automatically.
5. Confirm forwarded ports are working without manual reconnect.
