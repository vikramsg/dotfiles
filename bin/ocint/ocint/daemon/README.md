# ocint Daemon

## Overview

The ocint daemon is a VM-wide control service for starting, observing, and
continuing OpenCode sessions. It accepts work from interchangeable channels,
stores orchestration state in its own SQLite database, and uses one shared
`opencode serve` process as the execution plane.

The first deployment supports GitHub issue discovery, Slack requests, and a
small web frontend. The maximum number of concurrent OpenCode sessions is
configurable.

OpenCode owns conversation history and agent execution. The control service
owns jobs, scheduling, channel mappings, authorization, and recovery.

## Architecture And Flow Diagrams

```text
 GitHub poller       Slack adapter       Web frontend       daemon.toml
       |                  |                   |                 |
       +------------------+-------------------+-----------------+
                                  |
                                  v
                +-------------------+
                |  control service  |
                | API + scheduler   |
                +---------+---------+
                     /          \
                    v            v
       +-------------------+  +--------------------+
       | control SQLite DB |  | repository manager |
       | jobs + leases     |  +---------+----------+
       +---------+---------+            |
                 |             managed mirrors and worktrees
        configured capacity             |
                 |                      |
                 +----------+-----------+
                            |
                            v
                +-------------------+
                |  opencode serve   |
                | sessions + events |
                +-------------------+
```

```text
 inbound event
      |
      v
 normalize and authorize
      |
      v
 deduplicate -> persist queued job
                       |
                       v
              scheduler claims lease
                       |
            running slots < capacity?
                 |           |
                no          yes
                 |           |
               wait          v
                     resolve configured repo
                              |
                              v
                    clone/fetch managed mirror
                              |
                              v
                       create worktree
                              |
                              v
                    create/resume session
                              |
                              v
                    stream status and events
                              |
                              v
                  completed / failed / cancelled
                              |
                              v
                     publish channel update
```

## Responsibilities And Boundaries

The control service:

- Normalizes channel events into channel-independent work requests.
- Loads and atomically reloads validated daemon configuration.
- Authorizes actors and repositories before accepting work.
- Provisions managed repository mirrors and job worktrees.
- Persists jobs before scheduling them.
- Enforces the global running-session limit.
- Creates, resumes, monitors, and cancels OpenCode sessions.
- Validates completed worktree changes against configured checks.
- Commits approved changes, pushes job branches, and creates or discovers pull
  requests idempotently.
- Maps external conversations to jobs and OpenCode sessions.
- Exposes an authenticated API for the frontend.
- Publishes progress and terminal results through channel adapters.
- Reconciles interrupted work after restart.

OpenCode:

- Loads project configuration for the selected directory.
- Persists sessions, messages, and parts in its own database.
- Executes prompts and tools.
- Streams session events.
- Leaves commit, push, and pull request publication to the control service.

The two databases are independent. The control service must not depend on
OpenCode's internal database schema.

## Configuration And Repository Provisioning

The daemon reads TOML configuration from `$XDG_CONFIG_HOME/ocint/daemon.toml`,
falling back to `~/.config/ocint/daemon.toml`. `OCINT_DAEMON_CONFIG` overrides
the resolved path.

Configuration defines:

- Repository names, remote URLs, and default branches.
- Managed mirror and worktree roots.
- Scheduler capacity.
- OpenCode server connection details.
- Slack channel-to-repository mappings.
- Repository and actor allowlists.
- Retry, timeout, and retention policies.
- Provider base URLs used by production and fake adapters.

Secrets do not belong in the TOML file. They are supplied through the
environment or systemd credentials.

The CLI makes configuration discovery and reload explicit:

```bash
ocint daemon config
ocint daemon config --path
ocint daemon reload
```

`ocint daemon config` displays the resolved paths and effective non-secret
settings. `--path` prints only the resolved configuration path for scripts.
`ocint daemon reload`, or `SIGHUP`, parses and validates the complete file
before atomically activating it. A failed reload leaves the previous
configuration active. Running attempts retain their configuration snapshot;
new work uses the newly activated configuration.

OpenCode requires the session directory to exist. Before creating a session,
the repository manager:

- Resolves the requested repository through the configured registry.
- Rejects repositories and paths outside configured allowlists and managed
  roots.
- Lazily clones a managed local mirror or fetches an existing mirror.
- Creates a unique branch and worktree for the job.
- Persists the resolved repository, revision, branch, and worktree path.
- Passes the existing worktree path when creating the OpenCode session.
- Retains the worktree while follow-up interaction is allowed, then removes it
  according to the configured retention policy.

GitHub requests carry their repository identity. Slack requests resolve it from
an explicit request or a configured channel mapping. The agent is not
responsible for cloning its own repository.

## Job Queue And SQLite State

The control database records:

- Source events and their idempotency keys.
- Jobs, priorities, states, and timestamps.
- Attempts, leases, heartbeats, and errors.
- Repository, directory, worktree, and branch metadata.
- OpenCode session IDs.
- Channel conversation and reply targets.
- Result artifacts such as commits and pull request URLs.

The core job lifecycle is:

```text
queued -> preparing -> running -> validating -> publishing -> completed
                         |           |             |
                         +---------> failed <-------+
                         +---------> cancelled
```

Claims and state transitions must use short atomic transactions. A worker may
claim a queued job only when the number of non-expired running leases is below
the configured capacity. SQLite should use WAL mode, a busy timeout, and local
persistent storage.

On startup, the control service reconciles active leases with OpenCode session
status. Stale leases are released, while interrupted jobs are retried or failed
according to an explicit retry policy.

## OpenCode Server Integration

`opencode serve` is a multi-directory server. The control service selects the
project for each request using OpenCode's directory request scope, then creates
or resumes a session through the HTTP API or generated SDK.

The integration needs these operations:

- Create a session for a directory.
- Submit a prompt asynchronously.
- Resume an existing session.
- Read session and message state.
- Subscribe to global or session events.
- Cancel an active session.
- Dispose directory-scoped server state when a worktree is retired.

Persisted sessions survive an OpenCode server restart, but active runners do
not. The control service therefore treats its own job state as authoritative
and reconciles incomplete attempts after OpenCode reconnects.

OpenCode does not enforce the configured capacity. All automated session
creation must pass through the control service scheduler.

## Publication And Permission Policy

OpenCode may edit files and run explicitly permitted development commands only
inside its assigned worktree. It does not commit, push, call `gh`, or create a
pull request. The control service validates the resulting changes and owns all
publication operations.

The OpenCode execution environment must not contain GitHub publishing
credentials. Production deployment uses separate execution and publication
credentials or OS-level identities so the OpenCode process cannot read the
publisher credential. The control service supplies publishing credentials only
to its publication component.

Headless execution uses explicit allow and deny rules rather than blanket
`--auto` approval. The initial policy:

- Allows file operations within the assigned worktree.
- Allows configured repository validation commands.
- Denies paths outside managed roots.
- Denies destructive Git operations, `git push`, `gh`, and unapproved network
  access.
- Rejects or escalates any permission request not explicitly allowed.

OpenCode permission rules are policy controls, not a security sandbox. Jobs
that process untrusted input require OS-level isolation in addition to these
rules.

## Channel Protocol And Adapters

Channel-specific payloads are parsed only inside adapters. The control service
receives a normalized work request:

```text
WorkRequest
  idempotency_key
  conversation_id
  actor
  repository
  text
  source
  source_metadata
```

Progress and results use a normalized update:

```text
WorkUpdate
  conversation_id
  job_id
  status
  message
  session_id
  artifact_url
```

An adapter authenticates its source, constructs `WorkRequest`, and publishes
`WorkUpdate`. Slack timestamps, GitHub issue numbers, HTTP acknowledgements,
and similar transport details do not enter scheduling or execution code.

Initial adapters are:

- GitHub polling for issues selected by configured labels.
- Slack events, preferably through Socket Mode when public ingress is absent.
- Web requests from the control frontend.
- An in-memory fake for unit tests.

## Control API And Frontend

The browser communicates only with the control service. OpenCode is not exposed
directly.

The API provides:

- Queued, running, and recent jobs.
- OpenCode sessions associated with each job, including session ID, server URL,
  and project or worktree path.
- Session messages and tool activity.
- A real-time event stream proxied from OpenCode.
- Follow-up prompts, cancellation, and retry actions.
- Links back to the originating Slack thread or GitHub issue.
- A copyable attach command for every running session.

```bash
opencode attach http://127.0.0.1:4096 \
  --dir /path/to/worktree \
  --session ses_example
```

The server URL, directory, and session ID are stored as separate fields; the
frontend derives the command from them. Credentials come from the local
environment and must not be embedded in the displayed command.

The control service applies authentication and authorization before proxying
session operations or events.

## Concurrency And Recovery

The scheduler has a configurable global capacity. Capacity is represented by
durable leases rather than an in-memory counter. This prevents a service
restart from silently exceeding the limit.

Jobs targeting the same checkout or branch require additional repository-level
serialization. Distinct worktrees may execute concurrently, but shared Git
administration and publication operations still require coordination.

Every external event and publication step must be idempotent. Reprocessing an
event may resume its existing job, but must not create duplicate jobs, branches,
or pull requests.

## Security And Operations

Run the control service and OpenCode under a dedicated unprivileged system user
and supervise both with systemd. Keep OpenCode bound to loopback and protect it
with a generated server password known only to the control service.

The control service should provide:

- Repository, organization, Slack workspace, channel, and actor allowlists.
- Enforcement that repository mirrors and worktrees stay under managed roots.
- Secret redaction in logs and stored errors.
- Graceful shutdown that stops new claims before cancelling active work.
- Per-job timeouts and cancellation of descendant processes.
- Separation of OpenCode execution credentials from publication credentials.
- CPU, memory, process, and file-descriptor limits.
- Structured logs and health checks.

A worktree separates concurrent changes but is not a security sandbox. Jobs
triggered by untrusted users or repositories require container, microVM, or
equivalent OS-level isolation.

## Testing Strategy

Unit tests use fake channel and agent-runtime implementations with temporary
SQLite state. They cover normalization, deduplication, state transitions,
capacity enforcement, lease expiry, retries, cancellation, and restart
reconciliation without Slack, GitHub, or OpenCode. They also cover XDG and
environment path resolution, configuration validation, atomic reload failure,
activation of valid reloads, publication idempotency, and denial of publication
operations to the agent runtime.

Integration tests run the control service against a fake OpenCode HTTP server
and verify event streaming, reconnect behavior, and API authorization.

End-to-end tests use stateful fake SaaS servers rather than mocks or patched
functions:

- A fake GitHub REST server stores repositories, issues, labels, comments,
  branches, and pull requests.
- A fake Slack server stores users, channels, threads, and messages, then sends
  correctly signed HTTP events or Socket Mode envelopes.
- A local bare Git repository acts as the remote repository.
- The real repository manager lazily clones or fetches that remote and creates
  disposable worktrees.
- Provider base URLs and signing secrets are injected through normal service
  configuration.
- Control endpoints seed provider state, inject failures, and expose resulting
  state for assertions.

```text
test seeds fake provider
          |
          v
real channel adapter -> real control service -> real SQLite queue
                                                |
                                                v
                                  fake or real OpenCode server
                                                |
                                                v
                              real adapter -> fake provider API
                                                |
                                                v
                                    test asserts provider state
```

The fake servers run over real localhost HTTP and WebSocket transports. They
support duplicate deliveries, invalid signatures, rate limits, API failures,
and dropped connections without contacting GitHub or Slack.

## Bootstrap Acceptance

The first real acceptance run uses a manual fake-channel request, the real
control database and scheduler, and a real shared OpenCode server. OpenCode
makes a small deterministic documentation change in a managed worktree. The
control service validates, commits, pushes, and creates the pull request in
`vikramsg/dotfiles` using the existing local `gh` authentication.

```text
manual fake-channel request
          |
          v
real SQLite queue and scheduler
          |
          v
real OpenCode session in managed worktree
          |
          v
control-service validation and publication
          |
          v
real GitHub pull request
```

This use of ambient `gh` authentication is limited to bootstrap acceptance.
Production publication uses isolated credentials as described above.

## Open Decisions

- Slack Socket Mode versus signed HTTP event ingress.
- FIFO scheduling versus priorities and per-channel fairness.
- Retry limits and which failures are retryable.
- Worktree retention for follow-up conversations.
- When local worktrees require stronger sandbox isolation.

## References

### OpenCode

- Repository: <https://github.com/anomalyco/opencode>
- Researched commit: `c69abee0c73253aebae65e87e4e1b9bfa8c38021`
- Multi-directory server entrypoint: `packages/opencode/src/cli/cmd/serve.ts`
- Directory and session routing: `packages/opencode/src/server/routes/instance/httpapi/middleware/workspace-routing.ts`
- Directory instance lifecycle: `packages/opencode/src/project/instance-store.ts`
- Session run state: `packages/opencode/src/session/run-state.ts`
- Server authentication: `packages/opencode/src/server/auth.ts`
- Generated SDK server support: `packages/sdk/js/src/v2/server.ts`
- GitHub Actions integration: `github/index.ts`

### Open SWE

- Repository: <https://github.com/langchain-ai/open-swe>
- Researched commit: `697adaa7efa409fd692d7e00f9bac470aa87cf2c`
- GitHub ingress: `agent/webhooks/github_routes.py`
- Slack ingress: `agent/webhooks/slack_routes.py`
- Durable dispatch: `agent/dispatch.py`
- Thread-bound sandbox lifecycle: `agent/server.py`
- Slack follow-up queueing: `agent/utils/thread_ops.py`
- Pull request publication: `agent/tools/open_pull_request.py`
- Stateful E2E SaaS harness: `tests/e2e/harness.py`
- In-memory Slack, GitHub, and Git state: `tests/e2e/fakes.py`
- Fake Slack and GitHub user interfaces: `tests/e2e/static/`

## Appendix: Protocol Learnings

### OpenCode

- One server process can host sessions for multiple directories. Project scope
  is selected per request rather than fixed at server startup.
- Session records are durable, while active runners, event subscriptions, and
  background execution state are process-local.
- Session IDs bind later requests to the session's persisted directory, which
  makes them suitable as the control service's execution handle.
- The HTTP API and generated SDK already provide session creation, prompting,
  cancellation, inspection, and event streaming.
- OpenCode has no durable job queue, global admission control, channel protocol,
  or production service manager. Those belong in the control service.
- Server authentication is process-wide rather than per project or user, so the
  control service must be the authorization boundary.

### Open SWE

- External transports should authenticate and normalize events before durable
  dispatch.
- Stable conversation keys let repeated messages find the same agent thread and
  workspace. GitHub issue IDs and Slack channel/thread pairs are examples.
- Ingress acknowledgement, durable persistence, and execution dispatch are
  separate concerns. Persistence must happen before an event is considered
  accepted.
- Source delivery IDs are required for deduplication. A deterministic thread ID
  prevents duplicate conversations but does not prevent duplicate runs.
- Long-running work needs durable status, completion feedback, heartbeats, and
  reconciliation for stuck attempts.
- A workspace or sandbox should be associated with a conversation so follow-up
  messages can continue the same branch and filesystem state.
- Publication must be idempotent, including lookup of an existing pull request
  before attempting to create another.
- Open SWE's use of process-local HTTP background tasks before durable LangGraph
  dispatch leaves a loss window; the control service should persist first.
- Open SWE's E2E harness demonstrates a useful fake-SaaS boundary: real
  application code talks over HTTP to stateful fake GitHub and Slack APIs, while
  tests seed and inspect provider state through control endpoints.
- The Open SWE harness redirects endpoints with test-time patches. The control
  service should instead make provider base URLs first-class configuration so
  the same E2E coverage requires no monkeypatching.

### Adopted Testable Protocols

Channel behavior is represented by a small outbound interface that publishes
normalized updates. Inbound adapters produce `WorkRequest` values. Tests replace
both sides with an in-memory fake.

OpenCode is represented behind an agent-runtime interface with operations to
start, resume, cancel, inspect, and subscribe to a session. Tests replace it
with a deterministic fake that emits configured events and failures.

Queue storage is represented behind job and lease operations. Tests use a real
temporary SQLite database so capacity and transaction behavior are exercised
without external services.
