# opener-tunnel

`opener-tunnel` owns the Mac-side browser socket and the tmux-visible SSH
process. LCH owns only the native LaunchAgent lifecycle.

```text
launchd
  `-- LCH service: lch-opener-tunnel
      `-- opener-tunnel run
          |-- configured Unix socket listener
          `-- tmux session: lch-opener-tunnel
              `-- only pane: exec <configured SSH argv>
```

Ghostty may attach as an optional tmux client, but no Ghostty tab must remain
open. Service lifecycle events go to the LCH-managed stdout/stderr logs. SSH
verbose output remains only in tmux pane history.

## Setup

```bash
just opener-tunnel
lch logs lch-opener-tunnel --follow
tmux attach -t lch-opener-tunnel
```

Configuration is repo-managed at `opener_tunnel/config.toml` and symlinked to
`~/.config/opener-tunnel/config.toml`. The existing private `vm` SSH alias
continues to provide connection identity; tunnel flags and `RemoteForward` are
assembled from opener-tunnel configuration.
