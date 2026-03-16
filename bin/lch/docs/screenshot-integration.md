# lch and screenshot integration

This document describes the boundary between the generic watcher orchestrator (`lch`) and the screenshot-domain CLI (`screenshot`).

## Ownership boundary

```text
screenshot owns                     lch owns
-------------------------------     ---------------------------------
screenshot_dir                      launchd labels
filename filters                    plist generation
                                    systemd user unit generation
clipboard history limit             install/uninstall/status/logs
clipboard history state             dispatch into screenshot command
sync config                         watch-path lookup invocation
macOS screenshot location apply
```

## Install-time interaction

```text
lch install lch-screenshot-clipboard
or
lch install lch-screenshot-sync
  -> get job definition
  -> run `screenshot watch-path`
  -> receive absolute screenshot directory
  -> on macOS: write LaunchAgent plist
  -> on Linux: write systemd user .path/.service units
        Label = com.vikramsg.dotfiles.lch-screenshot-clipboard
          or  = com.vikramsg.dotfiles.lch-screenshot-sync
   -> activate with launchctl (macOS) or systemctl --user (Linux)
```

## Runtime interaction

```text
file written to screenshot_dir
  -> launchd/systemd path trigger wakes lch job
  -> `lch run lch-screenshot-clipboard`
  -> `screenshot clipboard on-event`
  -> screenshot finds newest matching screenshot
  -> screenshot copies absolute path to clipboard
  -> screenshot updates last-5 history state
  -> optional source-machine flow: `lch run lch-screenshot-sync` -> `screenshot sync run`
```

## State and command contract

```text
lch contract with screenshot
  watch-path command: screenshot watch-path
  dispatch commands:
    screenshot clipboard on-event
    screenshot sync run

screenshot state file
  ~/.local/state/screenshot/clipboard-history.json
  {
    "history": [
      "/Users/.../Desktop/Screenshots/Screen Shot ...png"
    ]
  }
```

Linux sink machines install only `lch-screenshot-clipboard`.
