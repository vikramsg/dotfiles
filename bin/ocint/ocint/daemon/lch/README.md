# ocint Daemon systemd Lifecycle

`ocint daemon lch` is the concrete Linux user-systemd surface:

```text
provision -> discover and validate -> write private config -> install units
install   -> validate existing config/env -> reload -> enable --now timer
status    -> report timer schedule, service result, and log path
logs      -> read the private rotating daemon log (--lines, --follow)
uninstall -> disable/stop -> remove only units -> reload
```

It generates exactly:

```text
$XDG_CONFIG_HOME/systemd/user/ocint-daemon.timer
$XDG_CONFIG_HOME/systemd/user/ocint-daemon.service
```

The timer uses `OnStartupSec=1m` relative to user-manager startup and
`OnUnitInactiveSec=15m` after each service invocation becomes inactive.
Reinstalling with `enable --now` can trigger immediately when the startup
deadline has elapsed. User lingering is required, and the mode-0600
`$XDG_CONFIG_HOME/ocint/daemon.env` must exist before installation.

Each invocation appends human-readable lifecycle, issue, job, and publication
events to `$XDG_STATE_HOME/ocint/daemon.log`. The mode-0600 log rotates at 10
MiB through five backups. `logs --lines N` reads across those backups, while
`logs --follow` follows the active file across rotation without using journald.

Provision must run from the target Git checkout root. It discovers GitHub, Git,
SSH, and OpenCode values, validates every input and destination before writes,
and uses only `gh auth token --hostname github.com` for the existing GitHub
token. See the [complete workflow](../../../docs/daemon/workflow.md).

Uninstall preserves configuration, credentials, auth symlink, database, logs,
mirrors, and worktrees. It never performs full cleanup or database deletion.
