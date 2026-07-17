# ocint Daemon Package

The daemon is a FastAPI application served directly by Uvicorn. It persists
jobs before scheduling them, runs OpenCode work behind a process-local capacity
semaphore, validates the result, and owns commit, SSH push, and idempotent
GitHub pull-request creation.

Documentation:

- [Complete daemon reference](../../docs/daemon.md)
- [Compact pull-request workflow](../../docs/daemon/workflow.md)
- [Future systemd roadmap](../../ROADMAP.md)

The package intentionally contains no custom HTTP server, scheduler polling
loop, Slack integration, distributed worker protocol, or systemd implementation.
