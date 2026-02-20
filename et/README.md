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

```bash
brew install MisterTea/et/et
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
    HostName <ip> 
    IdentityFile /path/to/key 
    # Force SSH to allocate a TTY (required for Tmux)
    RequestTTY yes
    # Automatically attach or create the dotfiles session
    RemoteCommand tmux new -A -s <session-name> 
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

