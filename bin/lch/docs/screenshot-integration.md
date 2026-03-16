# lch and screenshot integration

This document describes the boundary between the generic `launchd` orchestrator (`lch`) and the screenshot-domain CLI (`screenshot`).

## Ownership boundary

```text
screenshot owns                     lch owns
-------------------------------     ---------------------------------
screenshot_dir                      launchd labels
filename filters                    plist generation
clipboard history limit             install/uninstall/status/logs
clipboard history state             dispatch into screenshot command
sync config                         watch-path lookup invocation
```

## Install-time interaction

```text
lch install lch-screenshot-clipboard
  -> get job definition
  -> run `screenshot watch-path`
  -> receive absolute screenshot directory
  -> write LaunchAgent plist:
       Label = com.vikramsg.dotfiles.lch-screenshot-clipboard
       WatchPaths = [<screenshot_dir>]
       ProgramArguments = [~/.local/bin/lch, run, lch-screenshot-clipboard]
  -> load plist with launchctl
```

## Runtime interaction

```text
native macOS screenshot UI
  -> file written to screenshot_dir
  -> launchd WatchPaths triggers lch job
  -> `lch run lch-screenshot-clipboard`
  -> `screenshot clipboard on-event`
  -> screenshot finds newest matching screenshot
  -> screenshot copies absolute path to clipboard
  -> screenshot updates last-5 history state
```

## State and command contract

```text
lch contract with screenshot
  watch-path command: screenshot watch-path
  dispatch command:   screenshot clipboard on-event

screenshot state file
  ~/.local/state/screenshot/clipboard-history.json
  {
    "history": [
      "/Users/.../Screenshots/Screen Shot ...png"
    ]
  }
```
