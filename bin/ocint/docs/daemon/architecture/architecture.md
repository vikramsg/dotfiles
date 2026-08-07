# Daemon Architecture

The daemon has two process lifecycles over one physical SQLite database. A
systemd user timer starts a bounded GitHub/job invocation, which exits after an
unchanged idle interval. Slack Events require an available webhook, so a second
coordinator process and its ngrok tunnel stay running.

See [Provider Interactions](provider-interactions.md) for the target call stack
between provider-neutral task coordination and platform adapters.

```text
 GitHub polling timer                         Slack Events API
        |                                           |
        v                                           v
 durable thread/task -> durable job        signed durable ingress
        |                                           |
        v                                           v
 worktree -> job OpenCode -> validate       coordinator conversation
        |                                   -> coordinator OpenCode
        v                                           |
 commit -> push -> pull request                       `-> Slack thread reply

                both -> shared daemon.sqlite
```

## Module Boundaries

| Module | Responsibility |
| --- | --- |
| `cli.py` | Click composition, concrete dependencies, and FastAPI lifespan |
| `config.py` | Aggregate TOML shape, daemon lifecycle policy, paths, and validation |
| `api.py` | Bearer authentication, control routes, and live attach metadata |
| `pull_request_job/` | Durable request, job state, policy, checkpoints, scheduling, and the complete publication workflow |
| `coordinator/` | Normalized messages, conversation/turn/delivery rules, context workspace, worker, and recovery |
| `opencode/` | OpenCode-owned config plus the independent process, session, prompt, status, and SSE adapter |
| `git/` | Git-owned config plus the independent mirror, worktree, validation, commit, and SSH push adapter |
| `github/` | Issue observation, authorization, replies, and pull requests |
| `slack/` | Slack Events/Web API models, signed ingress, translation, actor classification, and reply delivery |
| `tasks/` | Provider-neutral thread, message, task, and retry coordination |
| `lch/` | Linux user-systemd setup and local operator commands |
| `db/` | Shared SQLite policy, schema, serialized migration lock, and one Alembic chain |

The CLI is the composition root. It translates the aggregate daemon config into
the narrow `pull_request_job` policy and injects the Git, OpenCode, and GitHub
gateways. Runtime pull-request-job code never receives `DaemonConfig`.

Feature facades expose configuration, gateway protocols, and construction
functions. Their factories construct concrete implementations when called.
Persistence factories receive the daemon database path and own their SQLAlchemy
engines internally; callers never pass an engine through a feature API.

```text
  cli.py
    |
    +--> bounded timer composition
    |     +--> Git + job OpenCode + GitHub polling
    |     `--> pull-request-job + task lifecycle
    |
    `--> always-on coordinator composition
          +--> signed Slack ingress + Slack delivery
          +--> restricted coordinator OpenCode
          `--> coordinator repository + worker

 api.py --------> pull_request_job <-------- tasks/
                       |
                       v
                 daemon.models
                  ^     ^     ^
                  |     |     |
               git/ opencode/ github/
```

Tasks own `task_job` associations but do not query the physical `job` table.
They pass candidate job IDs through their consumer-owned pull-request-job
gateway, which decides whether a completed job is reusable.

## Process Topology

```text
ocint-daemon.timer
  `-> ocint-daemon.service (oneshot)
        +-> GitHub polling
        +-> control API 127.0.0.1:8732
        `-> job OpenCode 127.0.0.1:4097

ocint-coordinator.service (Type=simple, restart on failure)
        +-> Slack ingress 127.0.0.1:8733
        +-> one coordinator worker
        `-> coordinator OpenCode 127.0.0.1:4098

ocint-coordinator-ngrok.service (Type=simple, restart on failure)
        `-> static HTTPS URL -> 127.0.0.1:8733

timer process + coordinator process -> shared daemon.sqlite
```

The two OpenCode runtimes have separate XDG config/data homes and separate
permission policies. The coordinator runtime lock admits one coordinator
process. This is not a distributed lease: the database still uses conditional
state transitions, but Phase 1 does not support multiple coordinator workers.

The complete execution path remains visible in one diagram:

```text
 GitHub issue thread
    |
    | transaction: observe messages and create an idempotent job
    v
 SQLite job table
    |
    | create asyncio task; wait for capacity semaphore
    v
 PullRequestJobRunner
    |
    +--> managed Git mirror
    |       |
    |       v
    |    isolated branch + worktree
    |       |
    |       v
    +--> OpenCode 1.18.15 session
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
    +--> close OpenCode
    `--> dispose feature-owned SQLite engines
```

## Startup

Before the bounded timer API reports ready, the job daemon:

1. Resolves and validates `daemon.toml`.
2. Requires the API and GitHub tokens.
3. Migrates the daemon database.
4. Starts a private OpenCode server and verifies its exact version.
5. Returns interrupted `running` jobs to `queued` without resetting stages.
6. Polls GitHub, then reconciles durable tasks.
7. Schedules persisted queued jobs.

A startup failure prevents the API from becoming ready.

The always-on coordinator separately validates configuration and Slack channel
access, takes its single-runtime lock, serializes any pending migration, safely
regenerates its context workspace, and starts OpenCode `1.18.15`. Only after
OpenCode health succeeds does it serve ingress on `127.0.0.1:8733` and recover
durable turns. An unexpected OpenCode child exit fails the service so systemd
can restart the whole coordinator. The coordinator installs SIGTERM/SIGINT
handlers before OpenCode startup. A shutdown requested while startup is blocked
cancels startup, closes OpenCode, restores the prior handlers, and exits
normally; an actual startup failure still closes OpenCode and fails the service.

The CLI constructs concrete Slack, OpenCode, repository, and ingress adapters.
The coordinator facade owns the runtime lock, child lifecycle, worker/ingress
supervision, process-signal registration, and bounded shutdown through generic
process and ingress contracts; the coordinator package does not depend on
Slack. The coordinator's signal-free ingress operation gives Uvicorn no process
signals and stops it only when the facade requests ingress shutdown. The generic
timer daemon uses normal Uvicorn signal ownership, including FastAPI lifespan
shutdown on SIGTERM/SIGINT.

## Persistence

The daemon database is independent from both OpenCode data homes. The daemon
never reads or migrates OpenCode's SQLite schema. The timer and coordinator use
the same configured `daemon.sqlite`, with foreign keys, WAL mode, short
transactions, uniqueness constraints, and a busy timeout.

```text
 provider mapping -> thread -> thread_message
                     |
                     `-> task -> task_message
                             `-> task_job -> job

 coordinator_event -> coordinator_conversation -> coordinator_turn
                                                   |
                                                   `-> coordinator_delivery
```

Messages are `actionable`, `unauthorized`, or `agent_response`. Task creation
atomically claims all pending actionable messages. Agent responses are retained
for idempotency but excluded from prompts.

The table ownership is intentional. Task and pull-request-job repositories own
their rows and are claimed only by the timer process. The coordinator repository
owns conversation, turn, response, and delivery transitions and is claimed only
by the coordinator process. Both rely on `db/` for physical schema and
connection policy; shared infrastructure does not become a domain repository.

GitHub polling and Slack Events are ingestion mechanisms, not separate
persistence systems:

```text
GitHub polling adapter ----\
                            -> normalized durable workflow state
Slack Events adapter ------/
```

Phase 1 routes Slack only to coordinator state. GitHub still routes to the
existing task/job workflow. Old Slack polling tables and their data remain in
the migration chain but are no longer composed into timer execution.

The migration chain remains explicit:

```text
20260716_create_daemon_control
        |
        v
20260717_add_github_issues
        |
        v
20260719_add_thread_execution_job
        |
        v
20260719_reset_thread_task_model
        |
        v
20260724_decouple_github_source_state
        |
        v
20260724_add_job_title
        |
        v
20260724_add_slack
        |
        v
20260807_add_coordinator
```

Migration startup is protected by a user-owned daemon migration lock derived
from the canonical database path. Either application process may request the
migration, but only one runs Alembic at a time and both wait for the same single
head before doing work.

## Jobs And Checkpoints

Job state describes scheduling and terminal outcome:

```text
queued -> running -> completed
                  \-> failed
```

The stage records the last durable execution boundary:

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

Thread work is batched independently from job attempts:

```text
pending messages -> atomically create task batch -> job attempt
       |                                      |
       | process restart ---------------------+
       v
execution -> validation -> commit -> push -> PR verify/create -> response
                                                            |
                                                            v
                                                 batch addressed
```

Each job persists a canonical human-readable title. GitHub work uses the issue
title and normalizes it to `ocint: <issue title>` without duplicating an existing
case-insensitive prefix. The daemon applies that value to the commit and pull
request. An idempotency key uniquely identifies a job. A repeated submission
returns the existing row. Pull-request publication is independently idempotent
by repository, head branch, and base branch.

## Execution

Each new job gets branch `ocint/<job-id>` in a managed worktree. The daemon, not
OpenCode, owns validation and publication:

```bash
<configured validation commands>
git add --all
git -c user.name=<author> -c user.email=<email> \
  commit --no-verify -m "ocint: complete job <job-id>"
git push --no-verify --set-upstream origin ocint/<job-id>
```

OpenCode receives the worktree path through `x-opencode-directory`. Prompt
submission checkpoints intent before HTTP submission. On restart, the daemon
inspects the existing messages and session status before deciding to submit,
wait, or advance. Completion requires a terminal assistant response and an idle
session.

Follow-up issue comments inherit the addressed task's session, worktree, branch,
and open pull request. A closed or merged owned pull request is reported and is
never replaced.

## Coordinator Conversations

One authorized Slack root creates one conversation and one deterministic
OpenCode session. Authorized thread replies become ordered turns in that same
session. Slack timestamps are converted to exact integer ordering keys without
floating point; immutable event identity breaks ties.

```text
Slack root ----------------> conversation ----------> OpenCode session
Slack reply ---------------^       |
                                   `-> ordered turns -> Slack root thread
```

A reply can arrive before its root. The repository stores it as
`awaiting_root`; when the authorized root arrives, all eligible messages become
turns in source order. Orphans expire after the configured retention period
without invoking OpenCode. Only one turn runs at a time, and an earlier deferred
turn blocks later turns in its conversation.

The OpenCode workspace is a generated fake/context directory containing
`AGENTS.md` and `repositories.json`. The catalogue is a safe projection of the
existing execution registry. There is no target checkout, repository tool, job
submission, Git operation, or GitHub publication path from the Phase 1
coordinator. Only coordinator output is delivered to Slack.

Slack models public `channel_type="channel"` and private
`channel_type="group"` messages as a normal typed union. Translation supports
both variants, but Phase 1 deployment is public-only: it subscribes to
`message.channels` and requests `channels:history`. Private subscription and
`groups:history` deployment remain unimplemented.

Every external effect has a durable intent. Prompt state records the stable
user-message ID before submission; the assistant message ID and full response
are persisted before delivery. Responses are split at paragraph, newline, then
whitespace boundaries into numbered chunks no larger than the configured 3,500
characters. All chunks are stored before the first post.

```text
received -> session_ready -> prompt_intended -> prompt_submitted
                                                  |
                                                  v
                                           response_ready
                                                  |
                                                  v
                                             delivering -> completed

recoverable state -> retry_not_before
unsupported/unauthorized -> ignored
```

Delivery uses deterministic `client_msg_id` values. Before repeating an
uncertain post, recovery searches the Slack thread and records a matching
existing reply. Chunks remain ordered and respect the configured per-channel
interval. HTTP 429 `Retry-After` and transient failures become durable retry
deadlines; a terminal OpenCode failure stores and delivers one safe response
without internal provider details. Recovery preserves the provider's typed
classification: a persisted terminal prompt error is never resubmitted, while a
retryable error or inactive incomplete prompt schedules durable observation
retry without adding another managed user message. The configured positive
turn retry budget counts schedules after the initial attempt, so a value of
three permits four total OpenCode attempts. Exhaustion persists and delivers
the safe failure response, terminally fails that turn, and unblocks the next
ordered turn. Only an absent managed prompt is submitted. Slack delivery
retries remain unbounded and preserve the response already stored for delivery.

## Recovery

| Persisted stage | Resume behavior |
| --- | --- |
| `execution` | Reuse the worktree and session; inspect the prompt before submission |
| `validation` | Run checks without rerunning OpenCode |
| `commit` | Commit the validated worktree |
| `push` | Push the existing commit |
| `pull_request` | Find or create the PR without pushing again |

Job recovery remains owned by the bounded timer process. Coordinator recovery
is independent: process restart resumes non-terminal turns and deliveries from
the same database, observes an intended prompt before deciding whether to
submit, and reconciles uncertain Slack posts before retrying. Concurrent access
is supported only in this domain-owned topology; do not run a second
coordinator worker.

## Shutdown

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

Uvicorn stops accepting timer API requests first. Active jobs receive the
configured shutdown grace. Remaining tasks are cancelled and requeued at their
current stage, then OpenCode and SQLite resources close. A hard kill skips
cleanup, but startup reconciliation recovers jobs left in `running`.

Coordinator shutdown stops ingress and the worker within its configured grace,
then closes coordinator OpenCode and restores the prior SIGTERM/SIGINT handlers.
Unexpected worker, ingress, or child completion wins over a concurrent requested
shutdown and fails the service; child exit retains its specific status.
The coordinator unit uses `KillMode=mixed`: systemd initially signals only the
main process, while timeout cleanup may terminate the remaining cgroup.
Cancellation does not move durable checkpoints, so systemd restart continues
from the last committed intent.

## Testing

```text
tests/unit/ocint/daemon/
tests/integration/ocint/daemon/
tests/e2e/ocint/daemon/
tests/live/ocint/daemon/coordinator/  # marked live; deselected by default
```

The deterministic suites cover stage transitions, recovery, API authentication,
signed ingress, response chunking, OpenCode HTTP/SSE behavior, real Git
worktrees, GitHub publication, systemd rendering, and production composition.
The live suite is invoked explicitly with `-m live` to exercise real Slack,
ngrok, and the restricted coordinator OpenCode sandbox; ordinary pytest
discovery deselects it.
