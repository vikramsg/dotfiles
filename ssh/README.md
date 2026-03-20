# SSH  

## SSH Config Inheritance

SSH config is matched top-to-bottom. For each key, the first value that matches is used.

Use this pattern:

- Put specific aliases first (`vm.dotfiles`, `vm.kunda`).
- Put shared base rules after (`vm`, `vm.*`).

Example:

```ssh-config
Host vm.dotfiles
    RemoteCommand /home/linuxbrew/.linuxbrew/bin/tmux a -d -t dotfiles

Host vm.kunda
    RemoteCommand /home/linuxbrew/.linuxbrew/bin/tmux a -d -t kunda

Host vm vm.*
    RequestTTY yes
    ServerAliveInterval 15
    ServerAliveCountMax 3
```

---

## Core SSH Options

- `HostName`: target server DNS/IP.
- `User`: remote user.
- `IdentityFile`: private key path used for auth.
- `IdentitiesOnly yes`: forces SSH to use only configured identities.
- `RequestTTY yes`: asks for interactive TTY.
- `RemoteCommand`: command run after login (for example tmux attach).
- `LocalForward`: local port -> remote destination tunnel.
- `RemoteForward`: remote port/socket -> local destination tunnel.
- `ExitOnForwardFailure yes`: fail early if any configured forward cannot bind.


## Resilient Connections

For laptop sleep/wake and network changes:

- `ServerAliveInterval 15` + `ServerAliveCountMax 3` makes dead sessions exit instead of hanging.
- `ExitOnForwardFailure yes` prevents half-broken reconnects.
- `autossh` supervises SSH and restarts when SSH exits.

Useful autossh flags/env:

- `AUTOSSH_POLL=30`: fast child-health checks.
- `AUTOSSH_GATETIME=0`: keep retrying even if initial reconnect attempt fails.
- `-M 0`: disable autossh monitor-port mode and rely on SSH keepalive behavior.

---

## Port Forwarding Patterns

When multiple SSH sessions run concurrently, avoid port collisions:

- Use exactly one forwarding-owner session for shared local ports.
- Run other sessions without forwards (or with `-o ClearAllForwardings=yes`).

If more than one session binds the same local ports, SSH fails with `Address already in use`.

### Unix Socket Forwards Need One Owner Too

This rule also applies to `RemoteForward` Unix sockets such as browser-opener bridges.

- Keep the socket forward on one long-lived owner alias only.
- Do not put the same socket `RemoteForward` on a broad host pattern such as `Host vm vm.*`.
- Make all helper sessions opt out with `-o ClearAllForwardings=yes`, including short-lived commands like `ssh vm "tmux list-sessions"`.

Why this matters:

- A short-lived helper session can inherit the same `RemoteForward` socket path as the owner session.
- With `StreamLocalBindUnlink yes`, that helper can replace the live socket path.
- When the helper exits, the original session does not automatically reclaim the filesystem path.
- The socket file may still exist, but clients will fail with `connection refused`.

Sanitized example:

```sshconfig
Host vm vm.*
    HostName <remote-host>
    IdentityFile ~/.ssh/<key>
    User <remote-user>

Host vm.owner
    RemoteForward /home/<remote-user>/.opener.sock /Users/<local-user>/.opener.sock
```

```bash
# Good: helper commands do not inherit forwards
ssh -o ClearAllForwardings=yes vm "tmux list-sessions"
ssh -o ClearAllForwardings=yes vm "tmux has-session -t <name>"
autossh -M 0 -o ClearAllForwardings=yes vm "tmux attach -d -t <name>"
```

---

## Remote SSHD Setup

Client-side settings are not enough. Remote sshd should aggressively clean up dead clients.

Run this on the remote Linux VM from that machine's dotfiles checkout:

```bash
just setup-ssh-forwarding
```

This writes `/etc/ssh/sshd_config.d/05-vm-resilience.conf` and sets:

- `StreamLocalBindUnlink yes`
- `ClientAliveInterval 15`
- `ClientAliveCountMax 3`

Then it validates sshd config, restarts sshd safely, and prints the effective values.

### Drop-in Order (Important)

`sshd` loads `/etc/ssh/sshd_config`, which includes `/etc/ssh/sshd_config.d/*.conf`.
For many keys, including `ClientAliveInterval`, the first obtained value wins.

On cloud images, `/etc/ssh/sshd_config.d/50-cloudimg-settings.conf` commonly sets:

- `ClientAliveInterval 120`

If your file is named `99-...`, it can lose to `50-...` for first-match keys.
That is why this setup uses `05-vm-resilience.conf`.

Verify effective server values:

```bash
sudo sshd -T | rg 'clientaliveinterval|clientalivecountmax|streamlocalbindunlink'
```

---

## Systemd and Long-Lived Sessions

For tmux/session persistence on many Linux servers:

```bash
loginctl enable-linger $USER
```

Without lingering, user processes can be cleaned up when SSH disconnects.

---

## VM + Ghostty Example

This repo's workspace file is `ghostty/workspaces/vm.toml`.

- Forwarding owner tab (`vm.dotfiles`):

```toml
command = "env AUTOSSH_POLL=30 AUTOSSH_GATETIME=0 autossh -M 0 vm.dotfiles"
```

- Non-owner tabs (clear inherited forwards):

```toml
command = "env AUTOSSH_POLL=30 AUTOSSH_GATETIME=0 autossh -M 0 -o ClearAllForwardings=yes vm.kunda"
```

Shared alias behavior is defined in `ssh/config.vm.shared`.

---

## Troubleshooting

### `Address already in use`

If you see:

`bind [127.0.0.1]:8080: Address already in use`

then multiple SSH/autossh sessions are trying to bind the same local port.

Fix:

1. Keep forwards on one alias only (forwarding owner).
2. Use `-o ClearAllForwardings=yes` for non-owner sessions.
3. Close stale local SSH sessions that already own those ports.

### Unix socket exists but clients get `connection refused`

If a forwarded Unix socket path still exists on the remote host but tools like `lazygit`, `gh browse`, or `xdg-open` fail with `connection refused`, the usual cause is a transient SSH session inheriting and replacing the same `RemoteForward` path.

Common pattern:

1. A long-lived owner session creates the socket forward.
2. A short-lived helper session also matches the same SSH host pattern and inherits that `RemoteForward`.
3. The helper session replaces the socket path and then exits.
4. The original session keeps running, but the socket path no longer points to its live listener.

Fix:

1. Move the Unix socket `RemoteForward` onto one owner alias only.
2. Add `-o ClearAllForwardings=yes` to helper SSH commands and non-owner tabs.
3. Reconnect the owner session so it recreates the socket cleanly.
4. Verify both the path and the listener state.

Useful checks:

```bash
ls -l ~/.opener.sock
ss -xl | rg 'opener.sock'
```

### Applied successfully but `clientaliveinterval` is still 120

Cause:

- An earlier drop-in (often `50-cloudimg-settings.conf`) set `ClientAliveInterval 120`.
- `sshd` kept that first value and ignored your later override for that key.

Fix:

1. Use an earlier drop-in filename for your override (for example `05-vm-resilience.conf`).
2. Re-run `just setup-ssh-forwarding`.
3. Verify with `sudo sshd -T | rg 'clientaliveinterval|clientalivecountmax|streamlocalbindunlink'`.

### Interpreting `lsof` for forwarded ports

Run:

```bash
lsof -nP -iTCP:5173,8080,8081,19876,54321,54323 -sTCP:LISTEN
```

Interpretation:

- Good: one `ssh` PID owns all forwarded ports.
- Each port appears twice (`127.0.0.1` and `[::1]`) because SSH listens on IPv4 + IPv6 loopback.
- `LISTEN` means local tunnel endpoints are active.

### Reconnected but tmux looks wrong

Use `tmux a -d -t <session>` so stale clients are detached on reconnect.

---

## Quick Command Reference

```bash
# Forwarding-owner interactive session
env AUTOSSH_POLL=30 AUTOSSH_GATETIME=0 autossh -M 0 vm.dotfiles

# Non-owner interactive session
env AUTOSSH_POLL=30 AUTOSSH_GATETIME=0 autossh -M 0 -o ClearAllForwardings=yes vm.kunda

# Inspect local forwarded port ownership
lsof -nP -iTCP:5173,8080,8081,19876,54321,54323 -sTCP:LISTEN

# Apply remote sshd resilience settings (run on remote VM)
just setup-ssh-forwarding

# Keep tmux/session processes alive across disconnects (run on remote VM)
loginctl enable-linger $USER
```
