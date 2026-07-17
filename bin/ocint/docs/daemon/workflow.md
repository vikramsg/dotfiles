# Daemon Pull Request Workflow

```text
ocint daemon run
        |
        v
Uvicorn -> FastAPI lifespan
        |
        +-- Alembic migration
        +-- OpenCode health check
        +-- schedule persisted incomplete jobs once
        |
        v
bearer-authenticated manual API
        |
        | persist, then schedule task
        v
SQLite job table -> capacity semaphore
        |
        v
managed mirror and worktree
        |
        v
OpenCode 1.17.20 HTTP/SSE
        |
        v
validation -> explicit-author commit -> SSH push
        |
        v
find matching PR or create one -> terminal checkpoint
```

The database has one `job` application table. A restart requeues nonterminal
running jobs while preserving their stage and external-effect checkpoints.
Reusing an idempotency key returns the original job.

The API exposes authenticated `GET /health`, `POST /api/jobs`, `GET /api/jobs`,
and `GET /api/jobs/{job_id}`. Status includes the OpenCode session, worktree,
attach command, commit, and pull request URL.

OpenCode cannot access SSH or GitHub credentials. Validation also receives no
publication credentials. Git is configured with an SSH remote, explicit
`SSH_AUTH_SOCK`, and explicit author name/email; the GitHub token is used only
for REST pull-request lookup and creation.

## Shutdown

Shutdown happens only when Uvicorn is asked to stop, such as `Ctrl-C`,
`SIGTERM`, or a process-manager stop. Uvicorn first stops accepting HTTP work,
then invokes FastAPI lifespan shutdown. The executor stops scheduling new jobs
and waits up to `shutdown_timeout_seconds` for active jobs. Tasks still running
after that deadline are cancelled and their jobs are returned to `queued` with
the current stage intact. OpenCode and SQLite resources close after executor
shutdown.
