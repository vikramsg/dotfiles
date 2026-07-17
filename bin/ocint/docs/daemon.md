# ocint Daemon

The ocint daemon is a local FastAPI service that turns an authenticated work
request into an isolated OpenCode session and, after validation, a GitHub pull
request. Uvicorn owns the HTTP server and process signals. FastAPI lifespan owns
application startup and shutdown.

```text
 operator
    |
    | ocint daemon submit
    v
 authenticated FastAPI API
    |
    | transaction: insert or return idempotent job
    v
 SQLite job table
    |
    | create asyncio task; wait for capacity semaphore
    v
 JobExecutor
    |
    +--> managed Git mirror
    |       |
    |       v
    |    isolated branch + worktree
    |       |
    |       v
    +--> OpenCode 1.17.20 session
    |       |
    |       v
    |    prompt + HTTP/SSE idle confirmation
    |       |
    |       v
    +--> configured validation commands
    |       |
    |       v
    +--> explicit-author Git commit
    |       |
    |       v
    +--> SSH push of ocint/<job-id>
    |       |
    |       v
    +--> find or create GitHub pull request
            |
            v
      completed job checkpoint

 Uvicorn shutdown
    |
    +--> stop accepting HTTP requests
    +--> FastAPI lifespan waits for active jobs
    +--> cancel and requeue jobs after shutdown timeout
    +--> close OpenCode and SQLite resources
```

## Scope

The daemon currently supports:

- Bearer-authenticated health, submit, list, and status endpoints.
- A durable, idempotent SQLite job queue.
- Configurable process-local execution capacity.
- Managed Git mirrors, branches, and worktrees.
- One shared OpenCode 1.17.20 server.
- Configured validation commands.
- Control-owned commit, SSH push, and GitHub pull-request creation.
- Stage checkpoints and single-process restart recovery.
- Graceful Uvicorn and FastAPI lifespan shutdown.

The daemon deliberately does not implement distributed workers, database
leases, retries, cancellation, follow-up prompts, workspace cleanup, Slack,
browser UI, or systemd installation. Future systemd work is tracked in
[`ROADMAP.md`](../ROADMAP.md).

## Modules

The implementation uses a small set of deep modules:

| Module | Responsibility |
| --- | --- |
| `cli.py` | Click commands, concrete dependency wiring, FastAPI lifespan, and `uvicorn.run()` |
| `config.py` | Typed TOML configuration, environment settings, repository registry, and validation |
| `api.py` | Bearer authentication and the four HTTP routes |
| `repository.py` | SQLite transactions, idempotent submission, checkpoints, queries, and reconciliation |
| `service.py` | Job models, narrow dependency protocols, capacity, execution stages, and shutdown draining |
| `opencode.py` | OpenCode health, sessions, prompts, status, and global SSE events |
| `git.py` | Managed mirrors/worktrees, validation processes, commits, and SSH pushes |
| `github.py` | Idempotent pull-request lookup and creation |
| `db/` | SQLAlchemy schema, SQLite engine policy, Alembic environment, and initial revision |

The CLI is the composition root. Services depend on narrow protocols declared
beside the workflow rather than importing concrete repositories or provider
clients.

## Startup

Run the daemon with:

```bash
export OCINT_DAEMON_CONFIG="$HOME/.config/ocint/daemon.toml"
export OCINT_DAEMON_API_TOKEN="<generated-control-token>"
export OCINT_DAEMON_OPENCODE_PASSWORD="<OpenCode-server-password>"
export OCINT_DAEMON_GITHUB_TOKEN="<GitHub-REST-token>"
export SSH_AUTH_SOCK="<control-only-ssh-agent-socket>"

ocint daemon run
```

`ocint daemon run` constructs the FastAPI application and calls `uvicorn.run()`.
There is no custom server implementation or signal supervisor.

Before Uvicorn starts, application construction:

1. Resolves and validates `daemon.toml`.
2. Requires the API, OpenCode, and GitHub tokens.
3. Requires `SSH_AUTH_SOCK`.
4. Rejects repositories that do not use SSH remotes.
5. Constructs the repository, OpenCode, Git, GitHub, and executor objects.

During FastAPI lifespan startup:

1. Alembic upgrades the control database to the daemon head revision.
2. The OpenCode client starts and verifies `/global/health`.
3. The expected OpenCode version is checked exactly.
4. Interrupted `running` jobs are returned to `queued` without losing stages.
5. Persisted queued jobs are scheduled once.
6. FastAPI reports lifespan startup complete, allowing Uvicorn to serve HTTP.

If migration or OpenCode health fails, lifespan startup fails and Uvicorn does
not expose a ready API.

## Configuration

The default configuration path is `$XDG_CONFIG_HOME/ocint/daemon.toml`, falling
back to `~/.config/ocint/daemon.toml`. `OCINT_DAEMON_CONFIG` overrides it.

The tracked example is [`config/daemon.example.toml`](../config/daemon.example.toml):

```toml
database_path = "/var/lib/ocint-control/control.sqlite"
mirror_root = "/var/lib/ocint-control/mirrors"
worktree_root = "/var/lib/ocint-worktrees"

[[repositories]]
name = "dotfiles"
remote_url = "git@github.com:vikramsg/dotfiles.git"
default_branch = "main"
github_repository = "vikramsg/dotfiles"
author_name = "ocint daemon"
author_email = "ocint@example.invalid"
actors = ["vikram_orbio_earth"]
checks = [
  ["just", "--justfile", "bin/ocint/justfile", "check"],
  ["just", "--justfile", "bin/ocint/justfile", "test"],
]

[scheduler]
capacity = 2
job_timeout_seconds = 3600
shutdown_timeout_seconds = 30
command_timeout_seconds = 900
command_output_bytes = 65536

[opencode]
server_url = "http://127.0.0.1:4096"
username = "opencode"
request_timeout_seconds = 30
expected_version = "1.17.20"

[api]
host = "127.0.0.1"
port = 8732

[github]
api_url = "https://api.github.com"
```

### Root Settings

| Setting | Meaning |
| --- | --- |
| `database_path` | Independent daemon SQLite database migrated by Alembic |
| `mirror_root` | Directory containing managed bare Git mirrors |
| `worktree_root` | Directory containing job worktrees |
| `repositories` | Allowed repository registry |

Mirror and worktree roots must differ.

### Repository Settings

| Setting | Meaning |
| --- | --- |
| `name` | Stable name accepted by API submissions |
| `remote_url` | SSH remote in `git@host:path` or `ssh://host/path` form |
| `default_branch` | Base branch used for provisioning and pull requests |
| `github_repository` | GitHub `owner/repository` used by the REST client |
| `author_name` | Commit author name applied through `git -c user.name=...` |
| `author_email` | Commit author email applied through `git -c user.email=...` |
| `actors` | Optional allowlist; an empty list permits any authenticated actor |
| `checks` | Commands run sequentially in the generated worktree |

Repository names must be unique. HTTP, HTTPS, file, and local-path remotes are
rejected so Git publication cannot silently use ambient credential helpers.

### Scheduler Settings

| Setting | Default | Meaning |
| --- | ---: | --- |
| `capacity` | `1` | Maximum concurrently executing job tasks |
| `job_timeout_seconds` | `3600` | Maximum execution time for one job |
| `shutdown_timeout_seconds` | `30` | Time allowed for active jobs during shutdown |
| `command_timeout_seconds` | `900` | Timeout for validation and Git subprocesses |
| `command_output_bytes` | `65536` | Maximum subprocess output retained in an error |

Capacity is enforced by an in-process `asyncio.Semaphore`. There is no scheduler
polling loop. A successful submission schedules its job immediately, while
lifespan startup schedules persisted incomplete jobs once.

### Environment Settings

| Variable | Consumer | Purpose |
| --- | --- | --- |
| `OCINT_DAEMON_CONFIG` | CLI and daemon | Explicit TOML path |
| `OCINT_DAEMON_API_TOKEN` | API and CLI | Bearer authentication |
| `OCINT_DAEMON_OPENCODE_PASSWORD` | OpenCode client | HTTP Basic authentication |
| `OCINT_DAEMON_GITHUB_TOKEN` | GitHub client | Pull-request lookup and creation |
| `SSH_AUTH_SOCK` | Managed Git commands | Clone, fetch, and push authentication |
| `PATH` | Validation and Git subprocesses | Executable discovery |
| `LANG` or `LC_ALL` | Validation and Git subprocesses | Locale |

Secrets do not belong in TOML.

Inspect resolved non-secret configuration with:

```bash
ocint daemon config
ocint daemon config --path
```

Run migration explicitly when diagnosing database setup:

```bash
ocint daemon migrate
```

Normal daemon startup also runs the migration through FastAPI lifespan.

## Control API

Every route requires the exact header:

```http
Authorization: Bearer <OCINT_DAEMON_API_TOKEN>
```

Cookies and query-string tokens are not accepted. Bind to loopback unless an
independent authenticated transport protects the API.

### Health

```http
GET /health
```

```json
{"status":"ready"}
```

The endpoint becomes available only after FastAPI lifespan startup completes.

### Submit

```http
POST /api/jobs
Content-Type: application/json
```

```json
{
  "idempotency_key": "daemon-bootstrap-v2-final",
  "actor": "vikram_orbio_earth",
  "repository": "dotfiles",
  "prompt": "Create the requested documentation file only."
}
```

The endpoint returns `202 Accepted`. It returns `403` when the actor is not
allowed and `400` for an invalid repository or request.

Submission first commits the job transaction. Only after persistence succeeds
does the executor create an asyncio task. If the process exits in that interval,
the next startup schedules the persisted queued job.

### List And Status

```http
GET /api/jobs
GET /api/jobs/<job-id>
```

Status responses contain:

```json
{
  "id": "77acceaee050427395b2498ec248d2b9",
  "state": "completed",
  "stage": "complete",
  "repository": "dotfiles",
  "session_id": "ses_example",
  "worktree_path": "/var/lib/ocint-worktrees/77ac...",
  "attach_command": "opencode attach http://127.0.0.1:4096 --dir /var/lib/ocint-worktrees/77ac... --session ses_example",
  "commit_sha": "237e22e...",
  "pull_request_url": "https://github.com/vikramsg/dotfiles/pull/185",
  "error": ""
}
```

The equivalent CLI commands are:

```bash
ocint daemon health
ocint daemon submit dotfiles "<prompt>" \
  --actor vikram_orbio_earth \
  --idempotency-key stable-key
ocint daemon list
ocint daemon status <job-id>
```

## Persistence

The control database is independent from OpenCode's database. The daemon does
not read OpenCode's SQLite schema.

Alembic owns daemon schema creation. Because the daemon schema remains
unreleased, its complete current shape is squashed into the initial revision:

```text
20260716_create_daemon_control
```

Do not add a new migration until deployed databases require upgrades.

The application schema contains one `job` table:

| Column group | Fields |
| --- | --- |
| Identity | `id`, unique `idempotency_key` |
| Request | `actor`, `repository`, `prompt` |
| Lifecycle | `state`, `stage`, `error`, timestamps |
| OpenCode | `session_id`, `server_url`, prompt checkpoints |
| Workspace | `worktree_path`, `branch`, `base_revision` |
| Publication | `commit_sha`, `pushed`, `pull_request_url` |

`ix_job_queue` indexes state and creation time. SQLite connections enable
foreign keys, WAL mode, and a busy timeout through the daemon engine policy.

## States And Stages

Job states describe scheduling and terminal outcome:

```text
queued -> running -> completed
                  \-> failed
```

Stages describe the durable execution checkpoint:

```text
execution
   |
   v
validation
   |
   v
commit
   |
   v
push
   |
   v
pull_request
   |
   v
complete
```

The state and stage are intentionally separate. A restarted job can return to
`queued` while retaining `push`, for example, so execution resumes without
rerunning OpenCode, validation, or commit.

## Idempotency

`idempotency_key` has a unique database constraint. Repeating a submission with
the same key returns the original job regardless of whether it is queued,
running, completed, or failed. It does not create another branch, session,
commit, or pull request.

GitHub publication is independently idempotent. Before creation, the client
queries open pull requests using repository owner, head branch, and base branch.
An existing match is returned instead of creating another pull request.

## Git Workspace

For the first job targeting a repository, Git operations are equivalent to:

```bash
git clone --mirror git@github.com:owner/repository.git <mirror-root>/<name>.git
git -C <mirror> config remote.origin.mirror false
git -C <mirror> rev-parse refs/heads/main
git -C <mirror> worktree add <worktree-root>/<job-id> \
  -b ocint/<job-id> <base-revision>
```

Existing mirrors update their origin and fetch the configured default branch.
Each job receives branch `ocint/<job-id>` and its own worktree.

The daemon, not OpenCode, runs validation and publication:

```bash
<configured validation commands>
git add --all
git -c user.name=<author> -c user.email=<email> \
  commit --no-verify -m "ocint: complete job <job-id>"
git push --no-verify --set-upstream origin ocint/<job-id>
```

Validation commands receive only `PATH`, `LANG`, and `CI=1`. Managed Git
commands additionally receive `GIT_TERMINAL_PROMPT=0` and the explicit
`SSH_AUTH_SOCK`. GitHub REST tokens are never placed in either subprocess
environment.

## OpenCode Integration

OpenCode runs as a separate loopback service with
`OPENCODE_SERVER_PASSWORD`. The daemon authenticates with HTTP Basic auth using
the configured username and `OCINT_DAEMON_OPENCODE_PASSWORD`.

The daemon uses these OpenCode 1.17.20 operations:

| Operation | Endpoint |
| --- | --- |
| Health/version | `GET /global/health` |
| List sessions | `GET /session` |
| Create session | `POST /session` |
| Read messages | `GET /session/{id}/message` |
| Submit prompt | `POST /session/{id}/prompt_async` |
| Inspect status | `GET /session/status` |
| Observe events | `GET /global/event` |

Every directory-scoped request sends the raw resolved worktree path in
`x-opencode-directory`. The daemon does not URL-encode that header.

Prompt submission records intent before calling OpenCode and records submission
after the HTTP call. On restart, existing messages and session status determine
whether to submit, wait, or advance. A prompt is complete only when an assistant
response exists and the session is idle.

The global SSE stream is filtered by directory and session. A directory-less
`server.connected` event is accepted as a global connection event. Completion
accepts `session.idle` or `session.status` with idle status. Premature SSE EOF
while the session remains busy reconnects until the request timeout; it never
advances the job as completed.

OpenCode configuration must deny shell and publication network tools. The
tracked policy is [`config/opencode.daemon.json`](../config/opencode.daemon.json).
OpenCode must not receive `SSH_AUTH_SOCK`, the GitHub token, or the daemon API
token.

## GitHub Pull Requests

After push, the GitHub client calls:

```http
GET /repos/<owner>/<repository>/pulls
    ?state=open
    &head=<owner>:ocint/<job-id>
    &base=<default-branch>
```

If no open pull request matches, it calls:

```http
POST /repos/<owner>/<repository>/pulls
```

```json
{
  "head": "ocint/<job-id>",
  "base": "main",
  "title": "ocint: complete job <job-id>",
  "body": "Automated by ocint daemon."
}
```

`OCINT_DAEMON_GITHUB_TOKEN` requires pull-request read/write access to configured
repositories. It is used only by the GitHub HTTP client. SSH authenticates Git
clone, fetch, and push.

## Credential Boundaries

| Credential | API | OpenCode | Validation | Git | GitHub REST |
| --- | ---: | ---: | ---: | ---: | ---: |
| Daemon API token | yes | no | no | no | no |
| OpenCode password | client only | server counterpart | no | no | no |
| SSH agent socket | no | no | no | yes | no |
| GitHub token | no | no | no | no | yes |

The daemon is an orchestration boundary, not an operating-system sandbox.
Worktrees isolate concurrent Git changes but do not isolate untrusted code.

## Failure Handling

Expected failures become terminal `failed` jobs with a bounded error message:

- OpenCode version mismatch or unhealthy startup prevents API readiness.
- Invalid actors or repositories fail before persistence.
- Job timeout records `job timed out`.
- Validation failure prevents commit and push.
- Git failure prevents later publication stages.
- GitHub failure leaves the job at `pull_request` for inspection.

There is no automatic retry endpoint. Operators inspect status and submit a new
idempotency key after correcting the cause.

Subprocess output is capped by `command_output_bytes`. Git and validation
subprocesses are terminated when `command_timeout_seconds` is exceeded.

## Restart Recovery

On lifespan startup, the repository changes interrupted `running` jobs to
`queued` without resetting their stage or checkpoints. The executor schedules
all queued IDs once.

Stage recovery behavior:

| Stage | Resume behavior |
| --- | --- |
| `execution` | Reuse worktree/session; inspect prompt and status before submitting |
| `validation` | Run configured checks without rerunning OpenCode |
| `commit` | Commit existing validated changes |
| `push` | Push the existing commit |
| `pull_request` | Find or create the PR without pushing again |

The daemon supports recovery from a single process restart. It does not support
multiple daemon processes sharing one database.

## Shutdown

Shutdown occurs when Uvicorn receives `Ctrl-C`, `SIGTERM`, or a process-manager
stop. It does not occur after a request, after a job, or when the daemon is idle.

The sequence is:

1. Uvicorn stops accepting new HTTP requests.
2. Uvicorn invokes FastAPI lifespan shutdown.
3. The executor rejects new schedules.
4. Active jobs may finish for `shutdown_timeout_seconds`.
5. Remaining asyncio tasks are cancelled.
6. Cancelled running jobs are returned to `queued` at their current stage.
7. The OpenCode HTTP session closes.
8. The SQLAlchemy engine is disposed.

A hard process kill cannot run lifespan cleanup. The next startup still
reconciles any job left in `running`.

## Testing

The retained test structure mirrors production modules:

```text
tests/unit/ocint/daemon/
tests/integration/ocint/daemon/
tests/e2e/ocint/daemon/
```

Coverage includes:

- Configuration and SSH-remote validation.
- Repository idempotency, explicit claim, requeue, and reconciliation.
- Capacity semaphore and shutdown timeout behavior.
- Every execution stage and stage-specific restart.
- Complete Alembic upgrade, downgrade, and re-upgrade schema comparison.
- Bearer-authenticated API submission, list, and status.
- Exact OpenCode HTTP/SSE behavior, EOF reconnection, and idle confirmation.
- Real local Git mirrors, worktrees, validation, commit, and push.
- Stateful GitHub lookup/create behavior over localhost HTTP.
- Production FastAPI/Uvicorn composition from API submission through PR result.

Run:

```bash
just --justfile bin/ocint/justfile check
just --justfile bin/ocint/justfile test
just --justfile bin/ocint/justfile smoke
```

## Real Acceptance

The V2 acceptance run used the committed daemon implementation, a new retained
SQLite database, a real OpenCode 1.17.20 server, the configured SSH remote, and
the GitHub API.

```text
Implementation commit: c8367b4
Job:                  77acceaee050427395b2498ec248d2b9
Session:              ses_090b5db38ffe7uEGQ5tanMJ4mC
Commit:               237e22e017da19a21112a0e4c46a243c83c2647a
Pull request:          https://github.com/vikramsg/dotfiles/pull/185
Evidence database:    /tmp/opencode/ocint-daemon-acceptance-v2-c8367b4/control/control.sqlite
```

The pull request targeted `main`, changed only
`bin/ocint/DAEMON_ACCEPTANCE_V2.md`, and contained exactly:

```text
daemon-bootstrap-v2: accepted
```

Submitting the same idempotency key again returned the same job, session,
commit, and pull request. Uvicorn was then stopped with `Ctrl-C`, which invoked
FastAPI lifespan shutdown; the API and OpenCode test ports closed and the
database remained available for inspection.

## Troubleshooting

### API does not become ready

Check OpenCode health and version:

```bash
curl --fail --user "opencode:$OPENCODE_SERVER_PASSWORD" \
  http://127.0.0.1:4096/global/health
```

Confirm all required environment variables and `SSH_AUTH_SOCK` are present.

### Submission returns 403

The submitted `actor` is not in the configured repository allowlist.

### Job fails during validation

Inspect `error` with `ocint daemon status <job-id>`, then run the configured
check directly from the retained worktree. Nothing is committed or pushed when
validation fails.

### Git authentication fails

Confirm the agent contains an identity and the remote is reachable:

```bash
ssh-add -l
git ls-remote git@github.com:vikramsg/dotfiles.git refs/heads/main
```

### Job remains queued after restart

Confirm the API is running and inspect `ocint daemon list`. Lifespan startup
schedules persisted queued jobs once. A job submitted directly into SQLite
after startup is not observed because there is intentionally no polling loop.

## Related Documents

- [`docs/daemon/workflow.md`](daemon/workflow.md): compact pull-request flow.
- [`ocint/daemon/README.md`](../ocint/daemon/README.md): package index.
- [`ROADMAP.md`](../ROADMAP.md): deferred systemd lifecycle.
