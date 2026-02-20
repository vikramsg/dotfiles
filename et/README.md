# Eternal Terminal (ET) & Remote Tmux Workflow

This guide details how to set up **Eternal Terminal (`et`)** for a roaming, persistent remote development experience, combining it with your Tmux `dotfiles` session on a GCP VM.

## The Problem with Standard SSH
Standard SSH uses a strict TCP connection tied to your laptop's current IP address. If you close your laptop, switch Wi-Fi networks, or briefly drop your VPN, the connection dies. Your terminal freezes, and you must reconnect and reattach to Tmux manually.

## Why Eternal Terminal (`et`)?
ET solves the roaming problem by establishing a custom TCP connection (default port 2022) *after* using SSH for the initial secure handshake.
*   **Persistent:** If your IP changes or you go offline, ET instantly resumes the session the moment you regain internet access. You don't even have to re-type a command; your cursor just starts working again.
*   **Better than Mosh:** Unlike Mosh (which uses UDP), ET uses TCP, meaning it fully supports **SSH Port Forwarding** and **SSH Agent Forwarding** natively.

---

## 1. Installation (Required on BOTH sides)

`et` must be installed on both your local Mac and your remote VM.

### Local (macOS)
```bash
brew install eternalterminal
```

### Remote (Ubuntu/Debian VM)
SSH into your VM one last time and run:
```bash
sudo add-apt-repository ppa:jgmath2000/et
sudo apt-get update
sudo apt-get install et
```

**⚠️ Important Firewall Note:**
Because ET uses a custom TCP connection, you **must open port 2022** for inbound TCP traffic on your GCP firewall rules for that VM.

---

## 2. Configuration & Aliasing

We can use your `~/.ssh/config` to abstract away the long GCP hostname, identity files, and even force it to automatically launch your `dotfiles` Tmux session.

### Step 2a: Update `~/.ssh/config`
Add a block like this to your local SSH config file to create a short alias (`vm`) and define the Tmux auto-attach behavior:

```ssh-config
Host vm
    # Your actual GCP VM IP or hostname
    HostName 34.89.152.146 
    IdentityFile /Users/vikramsingh/.ssh/google_compute_engine
    UserKnownHostsFile=/Users/vikramsingh/.ssh/google_compute_known_hosts
    HostKeyAlias=compute.3281124291587027778
    IdentitiesOnly=yes
    # Force SSH to allocate a TTY (required for Tmux)
    RequestTTY yes
    # Automatically attach or create the dotfiles session
    RemoteCommand tmux new -A -s dotfiles
```

*Note: If you just run standard `ssh vm` now, it will connect and drop you right into the Tmux session.*

### Step 2b: Create a Shell Alias (Optional but Recommended)
While `et` can read your SSH config to resolve the IP and keys, it sometimes prefers the command to be passed explicitly. To make your morning routine as fast as possible, add this alias to your local `~/.zshrc` (or `.bashrc`):

```bash
alias vm="et vm -c 'tmux new -A -s dotfiles'"
```

---

## 3. The Daily Workflow

1.  Open your local terminal.
2.  Type `vm` (or `et vm -c "..."`).
3.  You are instantly dropped into your persistent Tmux session.
4.  Close your laptop, go to a coffee shop, open it back up.
5.  Start typing. ET resumes the connection in milliseconds.

## Tmux Quality of Life Settings (Already Applied)
To ensure copy/pasting and git pushes work seamlessly inside this remote Tmux session, your `tmux.conf` already includes two critical settings:

1.  **`set -g set-clipboard on`**: Enables OSC52. When you copy text inside Neovim/Tmux on the remote VM, it is securely forwarded over the connection directly into your local Mac's clipboard.
2.  **`set -g update-environment "SSH_AUTH_SOCK"`**: Ensures that if you detach and reattach (or ET resumes a session), your local SSH keys (like your GitHub key) are correctly forwarded into the Tmux environment so `git push` continues to work without permission denied errors.