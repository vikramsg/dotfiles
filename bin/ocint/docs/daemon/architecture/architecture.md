# Daemon Architecture

The daemon is a bounded orchestration process. A systemd user timer starts one
invocation, that invocation reconciles durable work, and the process exits after
an unchanged idle interval. It is not a permanently running queue worker.

See [Provider Interactions](provider-interactions.md) for the target call stack
between provider-neutral task coordination and platform adapters.

```text
 labelled GitHub issue
          |
          v
 GitHub observation -> durable thread/task -> durable job
                                              |
                                              v
 managed mirror -> isolated worktree -> OpenCode session
                                              |
                                              v
                       validate -> commit -> push -> pull request
```

## Module Boundaries

| Module | Responsibility |
| --- | --- |
| `cli.py` | Click composition, concrete dependencies, and FastAPI lifespan |
| `config.py` | Aggregate TOML shape, daemon lifecycle policy, paths, and validation |
| `api.py` | Bearer authentication, control routes, and live attach metadata |
| `pull_request_job/` | Durable request, job state, policy, checkpoints, scheduling, and the complete publication workflow |
| `opencode/` | OpenCode-owned config plus the independent process, session, prompt, status, and SSE adapter |
| `git/` | Git-owned config plus the independent mirror, worktree, validation, commit, and SSH push adapter |
| `github/` | Issue observation, authorization, replies, and pull requests |
| `slack/` | Signed Events API ingress, public-channel translation, actor classification, and delivery |
| `tasks/` | Provider-neutral thread, message, task, and retry coordination |
| `coordinator/` | Provider-neutral chat authorization, durable conversation turns, OpenCode correlation, and delivery recovery |
| `lch/` | Linux user-systemd setup and local operator commands |
| `db/` | SQLite policy, schema, and Alembic migrations |

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
   +--> Git facade factory
   +--> OpenCode facade factory
   +--> GitHub publisher/source factory
   +--> pull-request-job store lifecycle
   `--> task coordinator lifecycle

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

Before Uvicorn reports ready, the daemon:

1. Resolves and validates `daemon.toml`.
2. Requires the API and GitHub tokens.
3. Migrates the daemon database.
4. Starts a private OpenCode server and verifies its exact version.
5. Returns interrupted `running` jobs to `queued` without resetting stages.
6. Polls GitHub, then reconciles durable tasks.
7. Schedules persisted queued jobs.

A startup failure prevents the API from becoming ready.

## Persistence

The daemon database is independent from OpenCode's database. The daemon never
reads or migrates OpenCode's SQLite schema. SQLite connections enable foreign
keys, WAL mode, and a busy timeout.

Coordinator prompts rely on the exact OpenCode 1.18.15 HTTP contract. ocint
supplies `messageID` to `prompt_async`, observes the returned user message with
that ID, and accepts only a completed assistant message whose `parentID` points
to that user message. The sanitized contract fixture records the request body
and returned message-list shape without credentials or conversation content.

```text
 provider mapping -> thread -> thread_message
                     |
                     `-> task -> task_message
                            `-> task_job -> job
```

Messages are `actionable`, `unauthorized`, or `agent_response`. Task creation
atomically claims all pending actionable messages. Agent responses are retained
for idempotency but excluded from prompts.

Legacy Slack polling tables remain in place so upgrades preserve existing data,
but no polling runtime is composed or exported. The separate coordinator stores
provider-neutral events, conversations, turns, and delivery intents. Its Slack
adapter verifies and translates callbacks, while private `group` messages remain
durable unsupported events.

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
        |
        v
20260810_complete_coordinator_message_identity
```

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

## Recovery

| Persisted stage | Resume behavior |
| --- | --- |
| `execution` | Reuse the worktree and session; inspect the prompt before submission |
| `validation` | Run checks without rerunning OpenCode |
| `commit` | Commit the validated worktree |
| `push` | Push the existing commit |
| `pull_request` | Find or create the PR without pushing again |

Recovery supports one daemon process. Multiple processes must not share one
daemon database.

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

Uvicorn stops accepting requests first. Active jobs receive the configured
shutdown grace. Remaining tasks are cancelled and requeued at their current
stage, then OpenCode and SQLite resources close. A hard kill skips cleanup, but
startup reconciliation recovers jobs left in `running`.

## Testing

```text
tests/unit/ocint/daemon/
tests/integration/ocint/daemon/
tests/e2e/ocint/daemon/
```

The suites cover stage transitions, recovery, API authentication, OpenCode
HTTP/SSE behavior, real Git worktrees, GitHub publication, systemd rendering,
and production composition.
