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

## Request delivery

The VM wrapper sends one newline-terminated HTTP or HTTPS URL and waits up to
10 seconds for a response. `OK` means the Mac browser command completed
successfully, not that the browser finished loading the page. Rejected requests
and browser-command failures receive an `ERROR: <reason>` response. Missing
acknowledgement is also a failure on the VM; install both the updated Mac
listener and VM wrapper together.

The listener allows 5 seconds to receive the URL, separately from its 250 ms
shutdown polling interval. SSH connects the Mac socket before completing its
channel-opening handshake with the VM, so URL delivery after socket acceptance
requires another network round trip. Browser dispatch is limited to 5 seconds.

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
