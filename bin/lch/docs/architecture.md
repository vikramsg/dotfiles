# lch architecture

`lch` is a thin `launchd` orchestrator. It does not own screenshot rules or state; it only translates job definitions into LaunchAgents and dispatch commands.

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
  -> compute plist/log paths from label
  -> write ~/Library/LaunchAgents/<label>.plist
  -> launchctl unload existing plist if present
  -> launchctl load new plist
```

## Runtime flow

```text
launchd WatchPaths event
  -> ProgramArguments: ~/.local/bin/lch run lch-screenshot-clipboard
  -> lch resolves dispatch command
  -> run: screenshot clipboard on-event
```
