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
clipboard history state             persist explicit watcher commands
sync config                         native lifecycle operations
macOS screenshot location apply
```

## Install-time interaction

```text
lch install lch-screenshot-clipboard
or
root setup enumerates `screenshot sync list`
  -> derive `lch-screenshot-sync-<source-id>`
  -> resolve `screenshot sync watch-path <source-id>`
  -> call `lch install-watcher` with the job ID, path, and direct command
  -> write and load the native watcher
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
  -> configured source watcher directly runs `screenshot sync run <source-id>`
```

## State and command contract

```text
lch contract with screenshot
  watch-path command: screenshot watch-path
  dispatch commands:
    screenshot clipboard on-event
    screenshot sync run <source-id>

screenshot state file
  ~/.local/state/screenshot/clipboard-history.json
  {
    "history": [
      "/Users/.../Desktop/Screenshots/Screen Shot ...png"
    ]
  }
```

Linux sink machines install only `lch-screenshot-clipboard`.

`screenshot/config.json` is the source of truth for sync sources. Root setup owns source enumeration and job naming; LCH remains domain-agnostic. Clipboard behavior remains separate.
