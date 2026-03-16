# lch architecture

`lch` is a thin native watcher orchestrator (`launchd` on macOS, `systemd --user` on Linux). It does not own screenshot rules or state; it only translates job definitions into OS watcher units and dispatch commands.

Its namespace configuration is repo-managed at `lch/config.json` and symlinked to `~/.config/lch/config.json`.

## Job ownership

```text
+------------------------------+
| lch jobs                     |
| job_id: lch-screenshot-...   |
| label: com.vikramsg.dotfiles |
| watch-path command           |
| dispatch command             |
+--------------+---------------+
               |
               v
+------------------------------+
| lch launchd layer            |
| - plist path                 |
| - stdout/stderr log paths    |
| - LaunchAgent payload        |
| - launchctl load/unload      |
+--------------+---------------+
               |
               v
+------------------------------+
| macOS launchd                |
| WatchPaths wakes lch         |
| ProgramArguments run         |
|   lch run <job_id>           |
+------------------------------+
```

## Install flow

```text
lch install lch-screenshot-clipboard
  -> resolve job metadata
  -> ask screenshot for watch path
  -> on macOS: write ~/Library/LaunchAgents/<label>.plist and load with launchctl
  -> on Linux: write ~/.config/systemd/user/<label>.{path,service} and enable path unit
```

## Runtime flow

```text
native watcher event
  -> ProgramArguments: ~/.local/bin/lch run lch-screenshot-clipboard
     or ~/.local/bin/lch run lch-screenshot-sync
  -> lch resolves dispatch command
  -> run: screenshot clipboard on-event
     or: screenshot sync run
```

On Linux sink machines, the installed watcher job is `lch-screenshot-clipboard` only.

## Discovery and pagination flow

```text
lch launchd list / lch launchd page
  -> scan LaunchAgents and LaunchDaemons roots
  -> parse plist files and read Label
  -> skip invalid or unlabeled plists
  -> classify agent vs daemon from source directory
  -> query launchctl for loaded status
  -> sort by label and plist path
  -> `launchd list` renders the full discovered dataset
  -> interactive pager for `launchd list`
  -> `launchd page` paginates rendered rows
  -> plain output for `launchd page`
```
