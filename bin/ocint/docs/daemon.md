# ocint Daemon

```text
 user systemd manager
   |
   | OnStartupSec=1m, then OnUnitInactiveSec=15m
   v
 ocint-daemon.service (one bounded invocation)
   |
   +-- private OpenCode server 127.0.0.1:4097
   |
   `-- authenticated FastAPI server 127.0.0.1:8732
          |
          +-- poll GitHub once
          +-- drain accepted issue/API work
          +-- wait for 60 seconds of unchanged idle state
          `-- stop both servers and exit
```

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

The ocint daemon is a bounded local FastAPI service that turns an authenticated work
request into an isolated OpenCode session and, after validation, a GitHub pull
request. Uvicorn owns the HTTP server and process signals. FastAPI lifespan owns
application startup and shutdown.

## Scope

The daemon currently supports:

- Bearer-authenticated health, submit, list, and status endpoints.
- A durable, idempotent SQLite job queue.
- Configurable process-local execution capacity.
- Managed Git mirrors, branches, and worktrees.
- One invocation-owned private OpenCode 1.17.20 server. Provisioning rejects
  every other installed version before writing managed files.
- Configured validation commands.
- Control-owned commit, SSH push, and GitHub pull-request creation.
- Stage checkpoints and single-process restart recovery.
- One GitHub issue poll per invocation, durable comment batching, and permanent
  issue-to-session/worktree/branch/pull-request ownership.
- A generated systemd user timer and one-shot service.
- Graceful Uvicorn, FastAPI, and OpenCode lifespan shutdown after unchanged idle.

The daemon deliberately does not implement distributed workers, database
leases, generic channels/providers, an outbox, replacement pull requests,
workspace deletion, Slack, or a browser UI. There are no credential or
configuration compatibility fallbacks.

## Modules

The implementation uses a small set of deep modules:

| Module | Responsibility |
| --- | --- |
| `cli.py` | Click commands, concrete dependency wiring, FastAPI lifespan, and `uvicorn.run()` |
| `config.py` | Typed settings, repository registry, path resolution, and validation |
| `api.py` | Bearer authentication and the four HTTP routes |
| `repository.py` | SQLite transactions, idempotent submission, checkpoints, queries, and reconciliation |
| `service.py` | Job models, narrow dependency protocols, capacity, execution stages, and shutdown draining |
| `opencode.py` | OpenCode health, sessions, prompts, status, and global SSE events |
| `git.py` | Managed mirrors/worktrees, validation processes, commits, and SSH pushes |
| `github/` | Issue polling, comment persistence/batching, exact issue-title PR creation, and responses |
| `lch/provision.py` | Typed checkout, GitHub, Git, SSH, and OpenCode discovery; validated writes |
| `lch/doctor.py` | Typed, redacted human/JSON diagnostics |
| `lch/systemd.py` | Exact user unit generation and lifecycle commands |
| `db/` | SQLAlchemy schema, SQLite engine policy, Alembic environment, and initial revision |

The CLI is the composition root. Services depend on narrow protocols declared
beside the workflow rather than importing concrete repositories or provider
clients.

## Startup

Provision from the root of the target Git checkout:

```bash
ocint daemon lch provision
ocint daemon doctor
```

Provision performs every discovery and validation before its first write. It
does not call `gh auth refresh` and never starts OAuth/device flow. The timer
later executes `ocint daemon run`, which owns both servers. There is no custom
server implementation or signal supervisor.

Before Uvicorn starts, application construction:

1. Resolves and validates `daemon.toml`.
2. Requires the API and GitHub tokens loaded from the mode-0600 environment file.
3. Rejects repositories that do not use SSH remotes.
4. Constructs the repository, private OpenCode child, Git, GitHub, and executor objects.

During FastAPI lifespan startup:

1. Alembic upgrades the control database to the daemon head revision.
2. The private OpenCode child starts and the client verifies `/global/health`.
3. The expected OpenCode version is checked exactly.
4. Interrupted `running` jobs are returned to `queued` without losing stages.
5. Persisted queued jobs are scheduled once.
6. GitHub is polled exactly once.
7. FastAPI reports lifespan startup complete, allowing Uvicorn to serve HTTP.

If migration or OpenCode health fails, lifespan startup fails and Uvicorn does
not expose a ready API.

## Configuration

The default configuration path is `$XDG_CONFIG_HOME/ocint/daemon.toml`, falling
back to `~/.config/ocint/daemon.toml`. `OCINT_DAEMON_CONFIG` overrides it.

The tracked example is [`config/daemon.example.toml`](../config/daemon.example.toml):

```toml
database_path = "~/.local/state/ocint/daemon.sqlite"
mirror_root = "~/.local/share/ocint/mirrors"
worktree_root = "~/.local/share/ocint/worktrees"

[[repositories]]
name = "repository"
remote_url = "git@github.com:OWNER/REPOSITORY.git"
default_branch = "main"
github_repository = "OWNER/REPOSITORY"
author_name = "ocint daemon"
author_email = "ocint@example.invalid"
actors = ["GITHUB_LOGIN"]
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
server_url = "http://127.0.0.1:4097"
username = "opencode"
request_timeout_seconds = 30
expected_version = "1.17.20"
executable = "/usr/local/bin/opencode"
config_file = "~/.config/ocint/opencode-xdg/opencode/opencode.json"
xdg_config_home = "~/.config/ocint/opencode-xdg"
xdg_data_home = "~/.local/share/ocint/opencode-data"

[api]
host = "127.0.0.1"
port = 8732

[github]
api_url = "https://api.github.com"
issue_label = "ocint"
agent_actor = "GITHUB_LOGIN"

[git]
ssh_executable = "/usr/bin/ssh"
identity_file = "~/.ssh/project-key"
known_hosts_file = "~/.ssh/known_hosts"
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
| `remote_url` | SSH remote in `user@host:path` or `ssh://user@host:port/path` form |
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
| `OCINT_DAEMON_GITHUB_TOKEN` | GitHub client | Pull-request lookup and creation |
| `PATH` | Validation and Git subprocesses | Executable discovery |
| `LANG` or `LC_ALL` | Validation and Git subprocesses | Locale |

Secrets do not belong in TOML. The OpenCode password is generated per
invocation. SSH uses the configured identity directly; `SSH_AUTH_SOCK` is not
forwarded.

Provisioning discovers configuration in this order and writes nothing until
all checks pass:

```text
 target checkout
   +-- isolated effective Git config --------> one push URL + owner/repository
   +-- gh api --hostname github.com user ----> login
   +-- gh repo view OWNER/REPOSITORY --------> canonical repo + default branch
   +-- gh auth token --hostname github.com --> token presence/value for env only
   +-- effective Git author -----------------> name/email
   +-- safe core.sshCommand + ssh -G --------> executable/key/known-hosts
   `-- XDG OpenCode config/auth -------------> model/provider + auth source
             |
             v
 validate remote equality, credentials, policy, ports, paths, linger, units
             |
             v
 atomically write managed files; auth remains a symlink
```

No compatibility source, default identity filename, personal login, repository,
home path, provider, model, or provider endpoint is built into provisioning.
All discovery subprocesses are bounded, receive closed stdin, disable prompts
and pagers, and omit ambient Git/GitHub repository-selection overrides.
SSH discovery carries the remote user and optional port into `ssh -G` as
`-l <user>` and `-p <port>`, so OpenSSH `Match` rules resolve against the same
destination Git will use.

Inspect resolved non-secret configuration with:

```bash
ocint daemon config
ocint daemon config --path
ocint daemon doctor
ocint daemon doctor --json
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
  "actor": "maintainer",
  "repository": "repository",
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
  "repository": "project",
  "session_id": "ses_example",
  "worktree_path": "$HOME/.local/share/ocint/worktrees/77ac...",
  "attach_command": "opencode attach http://127.0.0.1:4097 --dir $HOME/.local/share/ocint/worktrees/77ac... --session ses_example",
  "commit_sha": "237e22e...",
  "pull_request_url": "https://github.com/OWNER/REPOSITORY/pull/PR_NUMBER",
  "error": ""
}
```

The equivalent CLI commands are:

```bash
ocint daemon health
ocint daemon submit repository "<prompt>" \
  --actor maintainer \
  --idempotency-key stable-key
ocint daemon list
ocint daemon status <job-id>
```

## Persistence

The control database is independent from OpenCode's database. The daemon does
not read OpenCode's SQLite schema.

Alembic owns daemon schema creation. The second revision preserves all existing
job rows while adding issue tracking:

```text
20260716_create_daemon_control
        |
        v
20260717_add_github_issues
```

The application schema contains the existing `job` table plus
`github_issue` and `github_issue_comment`:

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

```text
 github_issue 1 ---- * github_issue_comment
      |
      `---- 1 permanent job
                |
                +-- one OpenCode session
                +-- one worktree and branch
                `-- at most one owned pull request
```

Human comment states are `pending`, `batched`, `addressed`, `rejected`, or
`errored`; marker-identified daemon comments are `agent`/`ignored`. The newest
comment in an active batch is its durable anchor. Earlier comments become
`batched`; the complete batch becomes `addressed` only after publication and
response persistence succeed.

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

```text
pending comments -> persist immutable prompt -> active anchor
       |                                      |
       | process restart ---------------------+
       v
execution -> validation -> commit -> push -> PR verify/create -> response
                                                            |
                                                            v
                                                 batch addressed
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

Validation commands receive only `PATH`, `LANG`, and `CI=1`. Local Git commands
receive `GIT_TERMINAL_PROMPT=0`. Network Git uses `BatchMode=yes`,
`IdentitiesOnly=yes`, the discovered identity, the discovered known-hosts file,
and strict host-key checking. GitHub REST tokens are never placed in any
subprocess environment, and no SSH agent fallback exists.

## OpenCode Integration

Each invocation starts OpenCode on private loopback port 4097 with an ephemeral
`OPENCODE_SERVER_PASSWORD`. The password is never persisted. Its allowlisted
environment points at isolated XDG config/data directories. The original
mode-0600 OpenCode auth file remains the source of truth and is symlinked into
the isolated data directory; it is never copied.

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
tracked policy is [`config/opencode.daemon.json`](../config/opencode.daemon.json),
the sole authoritative static policy. A tracked package symlink points to that
source; Hatchling dereferences it into the wheel as byte-identical
`ocint/daemon/opencode.daemon.json`, and runtime loads only that
`importlib.resources` resource. Provision preserves that policy and adds only the
selected model/provider's safe typed fields and the resolved worktree allow
rule. Provider secrets are not copied.
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
  "title": "<persisted GitHub issue title, byte-for-byte>",
  "body": "Automated by ocint daemon."
}
```

The initial pull request title is exactly the persisted issue title. Generic
executor titles are ignored for issue-owned publication. Follow-ups push the
same branch and reuse the same open PR; a closed or merged PR is reported on
the issue and is never replaced.

`OCINT_DAEMON_GITHUB_TOKEN` requires pull-request read/write access to configured
repositories. It is used only by the GitHub HTTP client. SSH authenticates Git
clone, fetch, and push.

## Credential Boundaries

| Credential | API | OpenCode | Validation | Git | GitHub REST |
| --- | ---: | ---: | ---: | ---: | ---: |
| Daemon API token | yes | no | no | no | no |
| Ephemeral OpenCode password | client only | server counterpart | no | no | no |
| SSH identity file | no | no | no | network Git only | no |
| GitHub token | no | no | no | no | yes |

The daemon is an orchestration boundary, not an operating-system sandbox.
Worktrees isolate concurrent Git changes but do not isolate untrusted code.

```text
 daemon.env: API token --------> FastAPI only
 daemon.env: GitHub token -----> GitHub HTTP client only
 auth.json symlink ------------> isolated OpenCode only
 SSH identity + known_hosts ---> network Git only
 ephemeral password -----------> daemon <-> child OpenCode
```

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

Shutdown occurs after the executor is idle for 60 seconds without an activity
generation change, or when Uvicorn receives `SIGTERM`/a process-manager stop.
Accepted API or GitHub work changes the generation; health, list, and status
reads do not.

The sequence is:

1. Uvicorn stops accepting new HTTP requests.
2. Uvicorn invokes FastAPI lifespan shutdown.
3. The executor rejects new schedules.
4. Active jobs may finish for `shutdown_timeout_seconds`.
5. Remaining asyncio tasks are cancelled.
6. Cancelled running jobs are returned to `queued` at their current stage.
7. The OpenCode HTTP session closes and the child receives terminate.
8. The child is killed only if its shutdown timeout expires.
9. The SQLAlchemy engine is disposed.

```text
wait executor idle -> snapshot generation -> sleep 60s
       ^                                      |
       | accepted work changed generation? ---+
       |
       ` no change and still idle -> request Uvicorn shutdown
                                      |
                                      v
                         drain -> close clients -> stop OpenCode
```

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

## systemd Lifecycle And Cleanup

`ocint daemon lch provision` generates exactly one timer and one service. The
timer's `OnStartupSec=1m` is relative to the user manager start, not wall-clock
boot. `OnUnitInactiveSec=15m` starts the next invocation after the previous
service becomes inactive. `enable --now` means reinstalling the timer can cause
an immediate trigger when the startup deadline has already elapsed.

`ocint daemon lch uninstall` disables/stops the units, removes only the two unit
files, and reloads systemd. It preserves configuration, environment, auth link,
database, mirrors, and worktrees. Full manual cleanup may remove managed config,
mirrors, and worktrees after inspection, but the database must be preserved
unless an operator separately backs it up and deliberately manages retention.

```text
bin/ocint/config/opencode.daemon.json -> packaged static policy
bin/ocint/config/daemon.example.toml  -> generic schema example
bin/ocint/docs/daemon.md              -> architecture/reference
bin/ocint/docs/daemon/workflow.md     -> from-scratch operations
ocint/daemon/lch/provision.py         -> discovery + writes
ocint/daemon/lch/doctor.py            -> redacted diagnostics
```

## Troubleshooting

### API does not become ready

Run the complete diagnostic and inspect service logs:

```bash
ocint daemon doctor
ocint daemon lch logs --lines 200
```

The private password is ephemeral and intentionally unavailable to shell
diagnostics. Startup allows 120 seconds for OpenCode health/version readiness.

### Provision asks for OAuth or device login

Stop. Provision must call only `gh auth token --hostname github.com`; it must
never refresh auth. Authenticate `gh` separately before retrying.

### Port conflict

The interactive OpenCode default often occupies 4096; that is independent.
The daemon requires private 4097 and API 8732. Stop the unexpected listener or
change the typed daemon API setting before provisioning. Doctor reports both.

### OpenCode reports a database lock

Confirm the service uses its isolated `xdg_data_home` and that the managed
`auth.json` is a symlink to the source auth file. It must not use the interactive
OpenCode database directory.

### Submission returns 403

The submitted `actor` is not in the configured repository allowlist.

### Job fails during validation

Inspect `error` with `ocint daemon status <job-id>`, then run the configured
check directly from the retained worktree. Nothing is committed or pushed when
validation fails.

### Git authentication fails

Inspect the effective SSH values with `ocint daemon doctor`. Provision derives
them from safe Git configuration and `ssh -G`; exactly one existing user-owned
mode-0600 identity and one readable known-hosts file must survive filtering.

```bash
GIT_SSH_COMMAND='/usr/bin/ssh -o BatchMode=yes' \
  git ls-remote git@github.com:OWNER/REPOSITORY.git refs/heads/main
```

### Journald cannot be read

Use `ocint daemon lch logs` as the same user that owns the user manager. Check
user journal permissions and that `systemctl --user` reaches that manager; do
not switch the service to a system unit as a workaround.

### Job remains queued after restart

Confirm the API is running and inspect `ocint daemon list`. Lifespan startup
schedules persisted queued jobs once. A job submitted directly into SQLite
after startup is not observed because there is intentionally no polling loop.

## Related Documents

- [`docs/daemon/workflow.md`](daemon/workflow.md): compact pull-request flow.
- [`ocint/daemon/README.md`](../ocint/daemon/README.md): package index.
- [`ROADMAP.md`](../ROADMAP.md): deferred systemd lifecycle.
