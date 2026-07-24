# ocint Daemon

The ocint daemon turns authorized, labelled GitHub issues into validated pull
requests. A systemd user timer starts one bounded invocation; the daemon drains
durable work and exits after an unchanged idle interval.

```text
 user systemd manager
   |
   | configured startup delay, then configured inactive interval
   v
 ocint-daemon.service (one bounded invocation)
   |
   +-- private OpenCode server 127.0.0.1:4097
   |
   `-- authenticated FastAPI server 127.0.0.1:8732
          |
          +-- poll GitHub
          +-- drain accepted issue work
          +-- wait for unchanged idle state
          `-- stop both servers and exit
```

```text
 GitHub issue or comment
     |
     | durable thread and task reconciliation
     v
 SQLite job -> isolated worktree -> OpenCode -> validation
                                                |
                                                v
                                      commit -> push -> PR
```

## What It Owns

- A durable, idempotent SQLite job queue.
- GitHub issue and comment observation with actor authorization.
- Managed Git mirrors, branches, and worktrees.
- One private OpenCode server per daemon invocation.
- Validation, commit, SSH push, pull-request publication, and issue replies.
- Restart recovery from durable execution checkpoints.
- Local systemd lifecycle, job inspection, logs, and live session attachment.

It deliberately does not provide distributed workers, leases, a browser UI,
workspace deletion, replacement pull requests, or generic provider plugins.

## Read Next

- [Minimal workflow](daemon/workflow.md): provision, request work, inspect, and attach.
- [Operations](daemon/operations.md): commands, job status, logs, and troubleshooting.
- [Configuration](daemon/configuration.md): provisioning, TOML, environment, and managed files.
- [Architecture](daemon/architecture.md): modules, persistence, stages, recovery, and shutdown.
- [Security](daemon/security.md): credential boundaries and live attach authentication.
- [Thread task specification](spec/daemon-thread-tasks.md): provider-neutral task rules.

## Source Map

```text
bin/ocint/docs/daemon.md                  -> this index
bin/ocint/docs/daemon/workflow.md         -> minimal operator path
bin/ocint/docs/daemon/operations.md       -> command reference
bin/ocint/docs/daemon/configuration.md    -> configuration reference
bin/ocint/docs/daemon/architecture.md     -> implementation model
bin/ocint/docs/daemon/security.md         -> authentication boundaries
bin/ocint/ocint/daemon/                   -> implementation
```
