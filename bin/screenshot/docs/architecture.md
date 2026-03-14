# screenshot architecture

`screenshot` is the single owner of screenshot-domain configuration, filtering, clipboard history state, and sync command construction.

## Internal ownership

```text
+---------------------------+
| screenshot config         |
| ~/.config/screenshot      |
| - screenshot_dir          |
| - filename_patterns       |
| - clipboard_history_limit |
| - sync.vm_host            |
| - sync.remote_dir         |
+-------------+-------------+
              |
              v
+---------------------------+
| screenshot clipboard      |
| - scan screenshot_dir     |
| - match filename filters  |
| - choose newest file      |
| - pbcopy absolute path    |
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

## Clipboard event flow

```text
directory change
  -> load screenshot config
  -> enumerate files in screenshot_dir
  -> filter by "Screenshot *.png" and "Screen Shot *.png"
  -> pick newest matching file by mtime
  -> if already history head: stop
  -> pbcopy absolute path
  -> prepend to history
  -> trim to clipboard_history_limit
```

## Sync flow

```text
screenshot sync run
  -> load screenshot config
  -> build rsync command
     rsync -avz
       --include=Screenshot *.png
       --include=Screen Shot *.png
       --exclude=*
       <screenshot_dir>/
       <vm_host>:<remote_dir>
  -> execute command
```
