# ocint Daemon Package

```text
daemon package -> concise index -> focused references -> lch operations
```

The daemon is a FastAPI application served directly by Uvicorn. It persists
jobs before scheduling them, runs OpenCode work behind a process-local capacity
semaphore, validates the result, and owns commit, SSH push, and idempotent
GitHub issue polling, exact-title pull-request creation, follow-ups, and bounded
two-server shutdown. Its application-owned rotating log records human-readable
lifecycle and job events under XDG state without relying on journald access.

Documentation:

- [Daemon documentation index](../../docs/daemon.md)
- [Minimal pull-request workflow](../../docs/daemon/workflow.md)
- [Operations and job inspection](../../docs/daemon/operations.md)
- [Architecture](../../docs/daemon/architecture.md)
- [Security and attach authentication](../../docs/daemon/security.md)
- [systemd lifecycle surface](lch/README.md)

`pull_request_job/` owns the durable end-to-end workflow. `git/` and
`opencode/` are independent sibling adapters, while `api.py` remains the single
inbound FastAPI adapter and `cli.py` composes their narrow facades.

The package intentionally contains no custom HTTP server, scheduler polling
loop, Slack integration, distributed worker protocol, generic lifecycle
framework, or compatibility credential fallback. `lch/` owns the concrete
Linux user-systemd implementation.
