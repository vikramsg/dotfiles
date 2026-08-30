# lch architecture

`lch` is a thin native orchestrator for existing path watchers and configured
macOS services. It does not own screenshot, opener, or application behavior; it
translates definitions into native jobs and dispatches commands or applications.

Its configuration is repo-managed at `lch/config.toml` and symlinked to
`~/.config/lch/config.toml`. Clipboard remains a static watcher and persistent
services come from the TOML `services` table. Domain-specific orchestration can
install a watcher by supplying its job ID, watch path, and dispatch command.

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

```text
lch install-watcher <job-id> <watch-path> <command>...
  -> derive the native label from the LCH namespace and job ID
  -> persist the explicit watch path and command in the native job
  -> load the native job
```

`lch list` merges configured definitions with installed native watcher identities
under the configured namespace and deduplicates them by job ID.

## Runtime flow

```text
native watcher event
  -> static watcher: ~/.local/bin/lch run lch-screenshot-clipboard
     -> lch resolves and runs screenshot clipboard on-event
  -> explicit watcher: run the command persisted by `lch install-watcher`
```

On Linux sink machines, the installed watcher job is `lch-screenshot-clipboard` only.

## Persistent service flow

```text
lch/config.toml [services.lch-opener-tunnel]
  -> lch install lch-opener-tunnel
  -> LaunchAgent: RunAtLoad + KeepAlive + ThrottleInterval
  -> lch run lch-opener-tunnel
  -> exec configured command: opener-tunnel run
```

Command services replace the `lch run` process and directly inherit launchd's
lifecycle and stdout/stderr.

```text
lch/config.toml [services.lch-macflow.application]
  -> lch install lch-macflow
  -> LaunchAgent: RunAtLoad + KeepAlive + ThrottleInterval
  -> lch run lch-macflow
  -> stop an existing current-user instance of the exact bundle executable
  -> LaunchServices opens the configured signed app bundle
  -> app stdout/stderr use the normal LCH log paths
  -> LCH waits for the app and terminates it when the service stops
```

The service configuration is an untagged union of command and application
services. The nested application definition is discriminated by `type`.
`type = "macos"` is implemented; `type = "linux"` is reserved and validated but
its runtime lifecycle is not yet implemented.

Persistent services have no `WatchPaths`. They are not added to systemd; the
existing Linux watcher path is unchanged.

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
