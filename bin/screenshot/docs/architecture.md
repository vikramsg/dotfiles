# screenshot architecture

`screenshot` is the single owner of screenshot-domain configuration, macOS screenshot location application, filtering, clipboard history state, and sync command construction.

Its repo-managed config source of truth is `screenshot/config.json`, symlinked to `~/.config/screenshot/config.json`.

## Internal ownership

```text
+---------------------------+
| screenshot config         |
| ~/.config/screenshot      |
| - screenshot_dir          |
| - filename_patterns       |
| - clipboard_history_limit |
| - sync.sources[]          |
|   - local_dir, filters    |
|   - vm_host, remote_dir   |
+-------------+-------------+
              |
              v
+---------------------------+
| macOS system location     |
| screenshot macos apply    |
| - mkdir screenshot_dir    |
| - defaults write location |
| - killall SystemUIServer  |
+-------------+-------------+
              |
              v
+---------------------------+
| screenshot clipboard      |
| - scan screenshot_dir     |
| - match filename filters  |
| - choose newest file      |
| - best-effort clipboard   |
| - update state history    |
+-------------+-------------+
              |
              v
+---------------------------+
| screenshot state          |
| ~/.local/state/screenshot |
| clipboard-history.json    |
| newest-first, max 5       |
+---------------------------+
```

On Linux, watcher orchestration is owned by `lch` (not `screenshot`). `lch` dispatches `screenshot clipboard on-event` when the configured watch path changes.

## Clipboard event flow

```text
directory change
  -> load screenshot config
  -> enumerate files in screenshot_dir
  -> filter by "Screenshot *.png" and "Screen Shot *.png"
  -> pick newest matching file by mtime
  -> if already history head: stop
  -> render shell-safe `~`-relative path for user-facing output
  -> try pbcopy, wl-copy, xclip (best effort)
  -> continue even if clipboard backend is unavailable
  -> prepend to history
  -> trim to clipboard_history_limit
```

## macOS apply flow

```text
screenshot macos apply
  -> load screenshot config
  -> mkdir -p screenshot_dir
  -> defaults write com.apple.screencapture location <screenshot_dir>
  -> killall SystemUIServer
```

## Sync flow

```text
screenshot sync list
  -> load screenshot config
  -> print each configured source ID

screenshot sync run <source-id>
  -> load screenshot config
  -> select configured sync source
  -> build rsync command from its filters and destinations
     rsync -avz
        --exclude=<configured patterns>
        --include=<configured patterns>
        --exclude=*
        <local_dir>/
        <vm_host>:<remote_dir>
  -> execute command
```
