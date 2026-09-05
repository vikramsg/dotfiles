# ocint Daemon

The ocint daemon has two deliberately different workflows. A timer-driven job
daemon turns authorized, labelled GitHub issues into validated pull requests.
An always-on coordinator answers authorized Slack threads from a restricted
context workspace. Phase 1 does not let Slack trigger repository execution.

```text
 user systemd manager
   |
   +-- ocint-daemon.timer
   |     `-- ocint-daemon.service (bounded)
   |           +-- poll GitHub
   |           +-- job OpenCode 127.0.0.1:4097
   |           `-- control API 127.0.0.1:8732
   |
   +-- ocint-coordinator.service (always on)
   |     +-- signed Slack ingress 127.0.0.1:8733
   |     `-- coordinator OpenCode 127.0.0.1:4098
   |
   `-- ocint-coordinator-ngrok.service (always on)
         `-- static HTTPS URL -> 127.0.0.1:8733

 all application processes -> one daemon.sqlite migration chain
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
- GitHub issue/comment polling and signed Slack Events ingestion.
- Managed Git mirrors, branches, and worktrees.
- Separate private OpenCode runtimes for jobs and coordinator conversations.
- Validation, commit, SSH push, pull-request publication, and issue replies.
- Durable Slack conversations, ordered turns, chunked replies, and restart recovery.
- Restart recovery from durable execution checkpoints.
- Local systemd lifecycle, job inspection, logs, and live session attachment.

It deliberately does not provide distributed workers, leases, a browser UI,
replacement pull requests, or generic provider plugins. The Phase 1
coordinator also cannot inspect, modify, validate, or publish a target
repository; only the coordinator replies to Slack.

## Read Next

- [Minimal workflow](daemon/workflow.md): provision, request work, inspect, and attach.
- [Operations](daemon/operations.md): commands, job status, logs, and troubleshooting.
- [Configuration](daemon/configuration.md): provisioning, TOML, environment, and managed files.
- [Architecture](daemon/architecture/architecture.md): modules, persistence, stages, recovery, and shutdown.
- [Security](daemon/security.md): credential boundaries and live attach authentication.
- [ngrok](daemon/ngrok.md): the dedicated static Slack Events tunnel.
- [Interactions](daemon/interactions.md): GitHub execution versus Slack conversation semantics.
- [Thread task specification](spec/daemon-thread-tasks.md): provider-neutral GitHub task rules.

## Source Map

```text
bin/ocint/docs/daemon.md                  -> this index
bin/ocint/docs/daemon/workflow.md         -> minimal operator path
bin/ocint/docs/daemon/operations.md       -> command reference
bin/ocint/docs/daemon/configuration.md    -> configuration reference
bin/ocint/docs/daemon/interactions.md     -> provider interaction semantics
bin/ocint/docs/daemon/ngrok.md            -> static Slack ingress tunnel
bin/ocint/docs/daemon/architecture/architecture.md -> implementation model
bin/ocint/docs/daemon/security.md         -> authentication boundaries
bin/ocint/ocint/daemon/                   -> implementation
```
