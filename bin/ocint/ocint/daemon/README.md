# ocint Daemon Package

```text
daemon package -> complete reference -> from-scratch workflow -> lch operations
```

The daemon is a FastAPI application served directly by Uvicorn. It persists
jobs before scheduling them, runs OpenCode work behind a process-local capacity
semaphore, validates the result, and owns commit, SSH push, and idempotent
GitHub issue polling, exact-title pull-request creation, follow-ups, and bounded
two-server shutdown.

Documentation:

- [Complete daemon reference](../../docs/daemon.md)
- [From-scratch pull-request workflow](../../docs/daemon/workflow.md)
- [systemd lifecycle surface](lch/README.md)

The package intentionally contains no custom HTTP server, scheduler polling
loop, Slack integration, distributed worker protocol, generic lifecycle
framework, or compatibility credential fallback. `lch/` owns the concrete
Linux user-systemd implementation.
