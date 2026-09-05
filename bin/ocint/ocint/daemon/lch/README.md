# ocint Daemon systemd Lifecycle

`ocint daemon lch` is the concrete Linux user-systemd surface:

```text
setup     -> create config when absent; provision policy/auth; install four units
apply     -> validate config/source; provision policy/auth; regenerate units
slack-token -> validate and install a Slack bot token from hidden input
lifecycle -> report timer, bounded service, coordinator, ngrok, and log state
list      -> list durable jobs directly from SQLite
status    -> show one durable job by ID
attach    -> authenticate and attach to one live OpenCode session
logs      -> read the private rotating daemon log (--lines, --follow)
uninstall -> disable/stop -> remove only units -> reload
```

LCH owns local daemon operations. The outer daemon command context loads and
validates `daemon.toml`, then passes resolved paths and policy into the adapter.
Job list and status read durable SQLite state even while the service is inactive.

It generates exactly:

```text
$XDG_CONFIG_HOME/systemd/user/ocint-daemon.timer
$XDG_CONFIG_HOME/systemd/user/ocint-daemon.service
$XDG_CONFIG_HOME/systemd/user/ocint-coordinator.service
$XDG_CONFIG_HOME/systemd/user/ocint-coordinator-ngrok.service
```

The timer renders daemon-owned `[lifecycle]` policy: its defaults are a
60-second startup delay relative to user-manager startup and a 600-second
inactive interval after each service invocation becomes inactive. Applying
with `enable --now` can trigger immediately when the startup deadline has
elapsed. Coordinator and ngrok units are installed but remain disabled so an
operator can run the autonomous live test before rollout. User lingering is
required, and the mode-0600 `$XDG_CONFIG_HOME/ocint/daemon.env` must exist
before installation.

The coordinator is a restarting `Type=simple` service. Its dedicated ngrok
service requires it and forwards the configured static URL to loopback port
`8733` with inspection disabled. Neither unit exposes the timer daemon's control
API (`8732`) or either OpenCode port (`4097` and `4098`).

Each invocation appends human-readable lifecycle, issue, job, and publication
events to `$XDG_STATE_HOME/ocint/daemon.log`. The daemon-owned `[logging]`
policy defaults to 10 MiB through five mode-0600 backups. `logs --lines N`
reads across those backups, while `logs --follow` follows the active file
across rotation without using journald.

Initial setup must run from the target Git checkout root. It discovers GitHub,
Git, SSH, and OpenCode values, validates every input and destination before
writes, and uses only `gh auth token --hostname github.com` for the existing
GitHub token. See the [complete workflow](../../../docs/daemon/workflow.md).

After creation, `daemon.toml` is user-owned. Setup reuses it byte-for-byte,
`apply` reads it without modifying it, and package reinstall and uninstall leave
it untouched. Every command reports concrete non-secret paths and outcomes.
Both setup and apply reject unsafe daemon/source OpenCode files before parsing or
writing. LCH does not generate coordinator context files; coordinator startup is
their single atomic owner, and also owns serialized database migration.
Token updates preserve unrelated `daemon.env` assignments and comments. The
Slack token command accepts interactive hidden input or piped stdin and never
places the token in argv or output.

Live attachment is different from offline inspection:

```text
daemon.env API token -> authenticated loopback request -> ephemeral password
                                                        |
                                                        v
                                              opencode attach process
```

The OpenCode password is never persisted. Read the
[security reference](../../../docs/daemon/security.md) for the complete flow.

Uninstall preserves configuration, credentials, auth symlinks, the shared
database and coordinator state, logs, context workspace, OpenCode data, mirrors,
and worktrees.
