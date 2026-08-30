# Bootstrap Macflow on a New Mac

This runbook installs Macflow on a new Mac and grants its required macOS
permissions to the installed application. Complete the permission and
verification sections before considering setup finished.

macOS does not allow Accessibility or Screen Recording access to be granted
silently. Both permissions require one-time approval in System Settings. Normal
rebuilds should retain those approvals because the installer preserves the
application's bundle identifier and designated signing requirement.

## Prerequisites

Macflow requires macOS 14 or later, Xcode Command Line Tools, Homebrew, `just`,
`uv`, and the applications referenced by `macflow/config.json`.

Install Xcode Command Line Tools if they are not already present:

```bash
xcode-select --install
```

Install Homebrew by following <https://brew.sh>, then install `just` and `uv`:

```bash
brew install just uv
```

Clone this repository and enter it:

```bash
git clone https://github.com/vikramsg/dotfiles.git
cd dotfiles
```

Install the repository's Homebrew dependencies:

```bash
just brew
```

## Install Supporting Services

Set up the shared screenshot directory and its XDG configuration:

```bash
just screenshot
```

Confirm that the directory is writable and the configuration is linked:

```bash
test -w /Users/Shared/Screenshots
test -L "${XDG_CONFIG_HOME:-$HOME/.config}/screenshot/config.json"
```

Install LCH before Macflow. Macflow uses LCH to install and supervise its
login service.

```bash
just lch
```

## Install Macflow

Build, sign, and install the application and CLI:

```bash
just macflow
```

The installation should create:

```text
~/Applications/Macflow.app
~/.local/bin/macflow
${XDG_CONFIG_HOME:-~/.config}/macflow/config.json
```

If `~/.local/bin` is not already on `PATH`, use
`$HOME/.local/bin/macflow` for the commands below until shell setup is
complete.

## Grant Accessibility

Request Accessibility access from the installed application:

```bash
macflow request-accessibility
```

Open **System Settings > Privacy & Security > Accessibility**, then enable
**Macflow**. If it is not listed, add this application explicitly:

```text
~/Applications/Macflow.app
```

Grant access to `Macflow.app`, not Terminal, Swift, the repository build
directory, or a standalone development executable. Accessibility is required
for window layouts, focus management, hotkeys, and synthetic input.

## Grant Screen Recording

Request Screen Recording access from the installed application:

```bash
macflow request-screen-recording
```

Open **System Settings > Privacy & Security > Screen & System Audio
Recording**, then enable **Macflow**. On macOS versions that label this section
**Screen Recording**, use that equivalent section.

Screen Recording is required for `macflow screenshot` and the screenshot HTTP
endpoint. Watching images created by another screenshot tool does not require
this permission.

## Restart After Approval

Restart the LCH-managed service so the running application observes the new
permissions:

```bash
lch install lch-macflow
```

## Verify Setup

Run every verification command:

```bash
macflow health
macflow permissions
lch status lch-macflow
macflow screenshot --preview
```

Setup is complete only when:

- `macflow health` returns a successful response.
- `macflow permissions` reports both Accessibility and Screen Recording as
  granted.
- `lch status lch-macflow` reports `loaded`.
- `macflow screenshot --preview` writes a PNG and displays its transient
  preview.

If a permission is still missing, confirm that the enabled entry points to
`~/Applications/Macflow.app`, enable it again if necessary, and repeat the
service restart and verification steps.

## Exercise Workflows

Verify the configured workflows after the command checks pass:

1. Press `cmd + shift + 1` and confirm Ghostty fills the usable screen.
2. Press `cmd + shift + 2` and confirm Zed fills the usable screen.
3. Press `cmd + shift + 3` and confirm Ghostty is left and Zed is right.
4. Press `cmd + shift + 4` and confirm Zed is left and Ghostty is right.
5. Press `cmd + shift + h` and confirm the screenshot shelf opens.
6. Drag a shelf thumbnail into Finder or another application and confirm the
   original file remains in the screenshot directory.
7. Close the shelf with Escape and confirm focus returns to the previously
   active window.
8. Create a screenshot and confirm the automatic transient preview appears.

## Preserve the Permission Identity

Macflow's macOS privacy approvals are associated with its installed application
identity. Do not casually rename the app, change its bundle identifier, alter
its designated signing requirement, or run a differently signed build in its
place.

The stable identity is:

```text
Application:            ~/Applications/Macflow.app
Bundle identifier:      dev.vikramsingh.dotfiles.mac-workflow
Designated requirement: identifier "dev.vikramsingh.dotfiles.mac-workflow"
```

Use `just macflow` for subsequent rebuilds and installations. It applies the
stable designated requirement expected to preserve the one-time TCC approvals.
