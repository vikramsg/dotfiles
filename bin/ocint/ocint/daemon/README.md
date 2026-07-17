# ocint Daemon

```text
request -> core policy -> adapter ports -> durable checkpoints
```

The daemon is a FastAPI application served directly by Uvicorn. It stores jobs
in an independent SQLite database, schedules submitted jobs immediately behind
an in-memory capacity semaphore, and checkpoints execution, validation, commit,
SSH push, and pull-request publication stages. Startup schedules persisted
incomplete jobs once without polling the database.

Manual work enters through the bearer-authenticated health, submit, list, and
status API. Submission commits the job before creating its execution task.

OpenCode 1.17.20 receives only directory-scoped HTTP/SSE requests. Validation
receives no publication credentials. Git network operations use only the
explicitly supplied SSH agent socket; local commits use the configured identity
without that socket. The GitHub token is used only by the idempotent
pull-request client.

Uvicorn owns process signals and HTTP shutdown. FastAPI lifespan runs the
Alembic migration, starts and health-checks OpenCode, schedules incomplete jobs,
and owns cleanup. On `Ctrl-C`, `SIGTERM`, or a process-manager stop, Uvicorn
stops accepting requests and invokes lifespan shutdown. Active jobs may finish
for `shutdown_timeout_seconds`; remaining tasks are cancelled and requeued at
their persisted stage before OpenCode and SQLite are closed.

There are deliberately no custom server supervisor, scheduler polling loop,
Slack integration, distributed runners, leases, attempts, retries,
cancellation, follow-ups, retention cleanup, generic channels, browser UI, or
systemd implementation.

The core settings model deliberately permits empty credentials. PR2 composition
will load configuration and reject missing credentials before starting adapters.
Repository registries, actor sets, and validation command sequences are deeply
immutable after typed configuration validation.
