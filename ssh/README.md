# SSH & Remote Development Workflows

This guide covers advanced configurations for `~/.ssh/config` to improve remote development, handle Tmux session auto-attachment, and build resilient connections using `autossh`.

---

## 1. SSH Config Inheritance (DRY Aliases)

You can use SSH config's top-down matching to create multiple, distinct connection aliases that all share the same underlying server details (IP, User, Keys).

The rule is simple: **The first time SSH sees a configuration key, it sets it and ignores future declarations.** Therefore, place your specific aliases at the top and your shared wildcard config at the bottom.

### Example `~/.ssh/config`
```ssh-config
# 1. Specific Session Aliases (These match FIRST)
# Use this to instantly connect and drop into your 'dotfiles' tmux session
Host vm-dotfiles
    RequestTTY yes
    RemoteCommand tmux new -A -s dotfiles

# Use this to instantly connect and drop into your 'backend' tmux session
Host vm-backend
    RequestTTY yes
    RemoteCommand tmux new -A -s backend

# 2. Base Configuration (This matches SECOND, filling in the blanks)
# All aliases starting with 'vm-' will inherit these settings
Host vm-*
    HostName <YOUR_SERVER_IP_OR_HOSTNAME>
    User <YOUR_REMOTE_USERNAME>
    
    # MUST be an absolute path if you plan to use background processes
    IdentityFile /Users/yourusername/.ssh/your_private_key
    IdentitiesOnly yes
    
    # (Add any other server-specific rules here)
```

With this setup, running `ssh vm-dotfiles` reads the `vm-dotfiles` block, applies the `RemoteCommand`, and then falls through to the `vm-*` block to get the IP address and SSH keys.

---

## 2. Resilient Port Forwarding with `autossh`

If you are roaming (changing Wi-Fi networks, putting your laptop to sleep) and need to maintain background port forwarding tunnels (e.g., `localhost:8080`), standard SSH will freeze and die. 

While `autossh` can automatically restart dead connections, it has two fatal flaws if not configured perfectly:
1. **The "Address Already in Use" Hang:** When reconnecting, the remote server might still hold the port from the previous, dead connection. `autossh` connects but the tunnel fails, and it hangs forever instead of retrying.
2. **Background Detachment Issues:** Running `autossh` in the background (`-f`) changes its working directory, causing relative paths to SSH keys to fail silently.

### The Bulletproof `autossh` Configuration

To fix these flaws, you must aggressively tune your `~/.ssh/config` and the command itself.

**1. Update `~/.ssh/config`**
Add these parameters to your host block to ensure SSH detects dead drops instantly and crashes cleanly if a port is stuck:

```ssh-config
Host vm-tunnel
    HostName <YOUR_SERVER_IP_OR_HOSTNAME>
    User <YOUR_REMOTE_USERNAME>
    # MUST BE ABSOLUTE PATH for backgrounding
    IdentityFile /Users/yourusername/.ssh/your_private_key
    
    # Detect dead connections immediately (Client side)
    ServerAliveInterval 5
    ServerAliveCountMax 2
    
    # CRITICAL: Fix the "Address already in use" hang
    # Forces SSH to crash if the port is stuck, triggering autossh to retry
    ExitOnForwardFailure yes
```

**2. The `autossh` Command**
Run this command to establish a resilient, backgrounded tunnel:

```bash
AUTOSSH_GATETIME=0 autossh -M 0 -f -N vm-tunnel -L 8080:localhost:8080
```

*   **`AUTOSSH_GATETIME=0`**: Tells `autossh` not to give up if the very first connection attempt fails (useful if running in a startup script before Wi-Fi connects).
*   **`-M 0`**: Disables autossh's internal (and outdated) ping method. We rely entirely on the superior `ServerAliveInterval` defined in the SSH config.
*   **`-f`**: Runs the process in the background.
*   **`-N`**: Do not execute a remote command (we just want the tunnel).

With this setup, if your laptop sleeps, the tunnel drops. When you wake it up, `autossh` aggressively retries until the remote server frees the port, re-establishes the tunnel in the background, and your local browser can access `localhost:8080` again without manual intervention.

