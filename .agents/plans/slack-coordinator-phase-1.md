# Slack Coordinator Phase 1 Plan

## Outcome

Phase 1 connects Slack to one always-running coordinator OpenCode sandbox.

```text
Slack private-channel thread
          |
          | Events API
          v
ngrok -> signed Slack ingress
          |
          | normalized conversation message
          v
shared daemon database
          |
          v
coordinator OpenCode sandbox
  - fake/context workspace
  - repository catalogue
  - web research
          |
          v
coordinator reply -> original Slack thread
```

Only the coordinator talks to Slack. Phase 1 has no repository execution
sandbox. The coordinator can answer, research, and explain that repository work
is needed, but it cannot trigger another OpenCode server or modify a repository.

The acceptance test is fully autonomous. The existing Slack bot posts a marked
test message, Slack delivers the real event through ngrok, the real coordinator
OpenCode sandbox runs, and the coordinator answer appears in the Slack thread.
No human posts a message or clicks anything during the test.

This plan supersedes `.agents/plans/slack-events-api-smoke.md` and the previous
version of this plan. External viability is already proven: Slack verified the
static ngrok URL, the signing secret authenticated a real Slack request, and
`message.groups` is subscribed.

## Corrected Architecture

### Polling And Events Are Input Mechanisms

GitHub polling and Slack Events API delivery are two ways to discover messages.
They are not different persistence domains:

```text
GitHub polling adapter ----\
                            -> normalized input -> durable workflow
Slack Events adapter ------/
```

Both use the existing daemon database infrastructure:

```text
                       daemon/db
             connection, WAL, migrations, schema
                          |
             +------------+-------------+
             |                          |
   existing task/job repositories   coordinator repository
```

There is one SQLite file and one migration chain. Do not create a coordinator
database.

Phase 1 connects Slack events to the coordinator workflow. The existing GitHub
polling and repository-job workflow remains operational. The normalized message
model must not contain Slack transport concepts, so a later change can route
GitHub-polled messages to the coordinator without changing coordinator state.
That later routing is not part of Phase 1.

### Repository Sandboxes Are OpenCode Runtimes

The future Phase 2 sandbox is not another persistence system. It is an OpenCode
HTTP server rooted in a repository workspace and configured with that
repository's tools and permissions:

```text
coordinator OpenCode
        |
        | select target and send prompt
        v
repository OpenCode server + repository workspace
        |
        | result
        v
coordinator OpenCode -> Slack
```

Phase 2 adds sandbox selection and another OpenCode call. Do not add a
delegation database, delegation table, queue, or speculative routing contract in
Phase 1.

## Coordinator Sandbox

The Phase 1 sandbox is one private OpenCode HTTP server rooted in a generated
fake repository/context workspace:

```text
~/.local/share/ocint/coordinator/
├── AGENTS.md
└── repositories.json
```

The workspace is not a checkout of `dotfiles` or another target repository.

`AGENTS.md` defines the coordinator's role:

- It is the sole conversational agent for Slack.
- It can answer questions and use web research.
- It knows which repositories are available from `repositories.json`.
- It cannot inspect or modify target repositories in Phase 1.
- It must not claim that repository work has been completed.
- If work is needed, it identifies the likely repository and objective and says
  repository execution is not available yet.
- It keeps responses concise and suitable for Slack.
- It asks follow-up questions in its normal response, not through an interactive
  OpenCode question tool.

`repositories.json` contains only safe routing context:

```json
{
  "repositories": [
    {
      "name": "dotfiles",
      "description": "Personal configuration for OpenCode, Neovim, tmux, and terminals.",
      "github_repository": "vikramsg/dotfiles",
      "default_branch": "main"
    }
  ]
}
```

It does not contain credentials, local target-repository paths, SSH remotes,
author identities, or validation commands.

The term sandbox describes the configured OpenCode boundary, not an operating-
system sandbox. The process runs as the daemon user. Phase 1 limits exposure by
denying shell commands, edits, external-directory access, plugins, and MCP while
allowing reads inside the context workspace plus web search/fetch.

## Conversation Model

One Slack root thread maps to one coordinator OpenCode session:

```text
Slack root ----------------> coordinator conversation ----> OpenCode session
Slack thread reply --------^                              |
                                                           v
                                                   accumulated context
```

- An authorized human root creates a conversation and OpenCode session.
- An authorized human thread reply creates another turn in the same session.
- Turns are processed in source-message order.
- Only one turn runs at a time in Phase 1.
- The final coordinator output returns to the Slack root thread.
- Bot-authored messages are ignored in production to prevent loops.
- Edits, deletions, file-only messages, unsupported subtypes, unconfigured
  channels, and unauthorized actors are durably ignored without OpenCode work.

The normalized inbound model is transport-neutral:

```text
ConversationIdentity
  provider
  workspace
  channel
  thread

ConversationMessage
  provider_event_id
  conversation_identity
  message_id
  actor_id
  text
  source_created_at
```

Slack constructs these values from event IDs and timestamps. The model does not
contain Slack request headers, retry numbers, bot tokens, or raw envelopes.

## Process Topology

The existing timer daemon remains bounded for GitHub polling. Slack requires an
always-available HTTP endpoint, so Phase 1 adds one separate process while both
processes use the same database infrastructure and file:

```text
ocint-daemon.timer
    `-> ocint-daemon.service (oneshot)
          +-> GitHub polling
          `-> existing task/job/repository OpenCode flow

ocint-coordinator.service (always on)
    +-> Slack ingress: 127.0.0.1:8733
    +-> coordinator worker
    `-> coordinator OpenCode: 127.0.0.1:4098

ocint-coordinator-ngrok.service (always on)
    `-> static public URL -> 127.0.0.1:8733

both application processes -> existing daemon.sqlite
```

SQLite WAL, short atomic transactions, uniqueness constraints, and the existing
busy timeout handle concurrent access. Phase 1 table ownership is explicit:

- The timer process continues claiming task/job rows.
- The coordinator process claims only coordinator conversation/turn/delivery
  rows.
- Both may insert normalized source messages through domain repositories.
- No coordinator transaction claims or changes a task/job row.

Database migration is a shared database-management responsibility. Protect
migrations with one daemon-owned filesystem lock so the timer and coordinator
cannot run Alembic concurrently. Each process may call migration at startup, but
only one performs it at a time and all workers start after the lock is released.

## Tidy, First

Perform only the preparation required for the new behavior:

1. **Database lifecycle:** put migration serialization in `daemon/db`, where
   connection policy and Alembic already live. Do not put migration logic in
   either workflow.
2. **OpenCode response:** extend the current OpenCode facade to return a stable
   assistant message ID and text. Existing PR jobs already submit and recover
   prompts but discard the response.
3. **Slack transport:** separate reusable Slack HTTP/authentication models from
   polling orchestration. Remove Slack from timer-daemon source composition
   before enabling coordinator events, preventing one Slack message from
   entering both workflows.

Do not refactor GitHub, Git, task, or pull-request-job behavior beyond removing
the Slack polling adapter from their composition.

## Module Ownership

```text
daemon/db/
  - one physical schema and migration chain
  - engine/WAL/foreign-key/busy-timeout policy
  - database mode and migration lock

daemon/coordinator/
  - config.py       coordinator policy
  - models.py       conversation, turn, delivery vocabulary
  - service.py      authorization, prompt, response chunking
  - repository.py   coordinator persistence operations
  - workspace.py    generated context workspace
  - run.py          worker, recovery, lifecycle
  - __init__.py     supported facade

daemon/slack/
  - config.py       workspace/channel authorization
  - models.py       Events API and Web API DTOs
  - events.py       signed HTTP ingress
  - client.py       Slack Web API transport
  - service.py      Slack translation and reply delivery
  - __init__.py     supported facade

daemon/opencode/
  - private process/HTTP adapter
  - response-bearing conversation operation

daemon/lch/
  - coordinator and ngrok systemd lifecycle
  - provisioning and diagnostics

daemon/cli.py
  - composition roots only
```

Dependency direction:

```text
Slack ingress -> normalized coordinator input <- coordinator worker
                                               |
                                               +-> OpenCode contract
                                               `-> Slack delivery contract

coordinator -> daemon/db
coordinator -X-> tasks
coordinator -X-> pull_request_job
coordinator -X-> git
coordinator -X-> github
coordinator -X-> daemon control API
```

Enforce these boundaries with Tach, not duplicate AST tests.

## Configuration

Add coordinator policy to the existing daemon TOML. Replace the polling-oriented
root `[slack]` runtime configuration; backward compatibility is not required for
this explicit architecture change.

Illustrative shape:

```toml
database_path = "~/.local/state/ocint/daemon.sqlite"

[coordinator]
workspace_root = "~/.local/share/ocint/coordinator"
turn_timeout_seconds = 1800
shutdown_timeout_seconds = 30
response_chunk_characters = 3500
slack_post_interval_seconds = 1

[coordinator.ingress]
host = "127.0.0.1"
port = 8733
max_request_bytes = 65536
timestamp_tolerance_seconds = 300

[coordinator.slack]
workspace_id = "T021N0EQ3JQ"

[[coordinator.slack.channels]]
channel_id = "C0955FD2FK4"
authorized_users = ["U067EG8278R"]

[coordinator.opencode]
server_url = "http://127.0.0.1:4098"
username = "opencode"
expected_version = "1.18.15"
executable = "/path/to/opencode"
config_file = "~/.config/ocint/coordinator-opencode-xdg/opencode/opencode.json"
xdg_config_home = "~/.config/ocint/coordinator-opencode-xdg"
xdg_data_home = "~/.local/share/ocint/coordinator-opencode-data"

[[coordinator.repositories]]
name = "dotfiles"
description = "Personal configuration for OpenCode, Neovim, tmux, and terminals."
github_repository = "vikramsg/dotfiles"
default_branch = "main"
```

Validation rules:

- The coordinator workspace differs from mirrors and worktrees.
- Coordinator and job OpenCode ports differ and are loopback-only.
- Ingress is loopback-only and differs from control API port `8732`.
- Slack channel IDs and repository catalogue names are unique.
- Authorized-user sets are non-empty.
- Slack workspace matches `auth.test`.
- Response chunk size leaves room below Slack's 4,000-character recommendation.
- Timeouts, body limits, and delivery intervals are positive.

Credentials remain in the existing mode-0600 daemon environment file:

```text
OCINT_DAEMON_SLACK_BOT_TOKEN
OCINT_DAEMON_SLACK_SIGNING_SECRET
OCINT_NGROK_URL
```

No package `.env` file is used.

### OpenCode Version Prerequisite

The VM currently runs OpenCode `1.18.15`, while existing daemon configuration
requires `1.17.20`. Before coordinator implementation:

1. Verify current session/message/status/SSE behavior against `1.18.15`.
2. Update the exact supported pin to `1.18.15` for both OpenCode runtimes.
3. Keep exact startup version checks; do not accept an arbitrary version range.
4. Re-run existing PR-job recovery tests.

## OpenCode Policy And Workspace

LCH creates private coordinator directories and atomically generates `AGENTS.md`
and `repositories.json`. It rejects symlinks and preserves mode `0700` on
directories and `0600` on generated files.

Add `config/opencode.coordinator.json` with this policy:

```text
share                 disabled
read/list/glob/grep   allowed inside coordinator workspace
websearch/webfetch    allowed
edit/write/patch      denied
bash/shell            denied
external_directory    denied
question              denied
plugins/MCP/LSP       disabled
```

The OpenCode child receives only isolated HOME/XDG paths, OpenCode provider
authentication, its ephemeral HTTP basic-auth values, PATH, and locale. It does
not receive Slack, ngrok, GitHub, daemon API, SSH, or Git credentials.

## Slack Ingress

The dedicated FastAPI app exposes only:

```text
POST /slack/events
```

It has no docs, generic proxy, daemon control routes, session-attach route, or
public OpenCode route.

Request handling:

1. Stream the raw body with a hard configured byte limit, even without
   `Content-Length`.
2. Require `X-Slack-Request-Timestamp` and `X-Slack-Signature`.
3. Reject timestamps outside the configured five-minute default.
4. Compute `v0=` HMAC-SHA256 over the exact raw body and compare in constant
   time.
5. Parse only after authentication.
6. Require the configured workspace.
7. Answer signed `url_verification` requests with the challenge.
8. Convert supported `event_callback` messages into normalized conversation
   messages.
9. Insert the event/message durably and atomically deduplicate it.
10. Wake the worker and return `200` without calling OpenCode or Slack Web API.

Slack requires a 2xx within three seconds. A database failure returns 5xx so
Slack retries. Duplicate event or message identity returns `200` without another
turn.

Do not store raw envelopes, signatures, deprecated verification tokens,
authorization arrays, or request headers.

## Shared Database And Persistence

Add coordinator tables to the existing `daemon/db/schema.py` and linear Alembic
migration chain:

```text
coordinator_event
  event_id                 primary key
  provider
  workspace_id
  channel_id
  thread_id
  message_id
  actor_id
  text
  source_created_at
  disposition
  created_at
  unique(provider, workspace_id, channel_id, message_id)

coordinator_conversation
  id                       primary key
  provider
  workspace_id
  channel_id
  thread_id
  opencode_session_id
  created_at
  updated_at
  unique(provider, workspace_id, channel_id, thread_id)

coordinator_turn
  id                       primary key
  event_id                 unique foreign key
  conversation_id          foreign key
  state
  managed_prompt
  assistant_message_id
  response_text
  error
  retry_not_before
  created_at
  updated_at

coordinator_delivery
  turn_id                  foreign key
  chunk_index
  client_msg_id            unique
  text
  state
  provider_message_id
  retry_not_before
  primary key(turn_id, chunk_index)
```

These tables share the physical database but remain coordinator-owned domain
state. Existing generic database management does not become a god repository:

- `daemon/db` owns schema, migrations, connection policy, and locks.
- Coordinator repository owns coordinator queries and state transitions.
- Task/job repositories continue owning task/job queries and transitions.

Turn state:

```text
received -> session_ready -> prompt_intended -> prompt_submitted
                                                |
                                                v
                                         response_ready
                                                |
                                                v
                                           delivering
                                                |
                                                v
                                           completed

received -> ignored
recoverable state -> retry_not_before
terminal error -> failed after safe response intent is persisted
```

Persist intent before every external effect. One coordinator worker claims the
oldest ready turn with an atomic transaction. Existing task/job claims remain
independent.

Migrations are additive. Preserve all existing Slack polling tables and data
even after polling code is no longer composed. Never delete or recreate a
database file during setup, testing, rollback, or uninstall.

## OpenCode Conversation Adapter

Extend the existing OpenCode adapter with a response-bearing operation while
preserving current job methods:

```text
create_or_reuse_session(workspace, identity) -> session_id
observe exact managed prompt
submit exact managed prompt
wait for terminal assistant and idle session
read completion -> assistant_message_id + text
```

Add stable message IDs to OpenCode wire models. Completion extraction finds the
terminal assistant after the exact latest managed user prompt and concatenates
its text parts in order. Tool output and internal reasoning are not sent to
Slack.

Managed prompt:

```text
Slack turn
workspace: <workspace id>
channel: <channel id>
thread: <root timestamp>
message: <message timestamp>
actor: <actor id>

<user text>
```

Recovery:

- Prompt absent: submit after persisting intent.
- Prompt present and active: wait.
- Prompt present and complete: read the existing assistant response.
- Prompt present but inactive/incomplete: use the existing interrupted-prompt
  recovery rule without silently adding a second logical turn.
- Persist assistant ID and full response before starting Slack delivery.

Session identity derives deterministically from provider/workspace/channel/root
thread. The database mapping is authoritative; OpenCode title lookup recovers a
session created before its checkpoint committed.

## Slack Response Delivery

Only coordinator output is delivered. Slack transport credentials remain in
the Slack adapter and never enter OpenCode.

Slack recommends at most 4,000 characters in `text`, truncates beyond 40,000,
and generally permits one post per second per channel. Handle all response sizes
without data loss:

1. Persist the full OpenCode response.
2. Split into chunks no larger than 3,500 characters including `[N/M]` numbering.
3. Prefer paragraph, newline, then whitespace boundaries.
4. Hard-split only when no boundary exists.
5. Count Unicode code points, not bytes.
6. Persist every chunk before posting the first.
7. Post plain text with link/media unfurling disabled.
8. Wait at least the configured per-channel interval between chunks.

Do not add file uploads or `files:write` in Phase 1. Ordered chunking preserves
the complete answer with the existing Slack scope.

Each chunk has a deterministic UUID `client_msg_id` based on turn and chunk
index. If Slack may have accepted a post before the local checkpoint committed,
recovery scans the thread for that ID and records the existing message rather
than posting a duplicate.

On HTTP 429, persist `Retry-After` and resume later. Never sleep or post from the
webhook request handler.

## Failure And Recovery

- Invalid signature, stale timestamp, malformed authenticated body, or oversized
  body: reject without state.
- Valid unsupported event: record ignored disposition and return `200`.
- Database unavailable: return 5xx for Slack retry.
- OpenCode transient failure: retain turn and retry with bounded backoff.
- OpenCode terminal failure or timeout: persist and deliver one safe coordinator
  failure response without provider details.
- Slack network/5xx failure: retain delivery for retry.
- Slack 429: honor durable `Retry-After`.
- Process restart: recover all non-terminal turns and deliveries in order.
- OpenCode child exit: fail the coordinator service; systemd restart recovers.
- Shutdown timeout: cancel memory work without moving the durable checkpoint.

## Production Lifecycle

Add two user-systemd units while preserving the existing timer units.

### `ocint-coordinator.service`

- `Type=simple`
- `UMask=0077`
- loads the existing `daemon.env`
- runs `ocint daemon coordinator run`
- restarts on failure with bounded delay
- starts after network availability
- starts ingress only after database migration and OpenCode health succeed

### `ocint-coordinator-ngrok.service`

- requires and starts after the coordinator unit
- forwards `${OCINT_NGROK_URL}` to `127.0.0.1:8733`
- disables ngrok HTTP inspection to avoid payload retention
- does not expose ports `8732`, `4098`, or `4040`
- restarts on failure

LCH setup/apply/status/doctor/uninstall manages both units alongside the existing
timer. Doctor validates config, private files, Slack `auth.test`, configured
channel access, signing-secret presence, ngrok config, exact OpenCode version,
workspace policy, port separation, migration head, and systemd payloads.

Uninstall removes units but preserves the shared database, coordinator rows,
workspace context, OpenCode data, credentials, and Slack messages.

## Autonomous Live E2E

The production policy ignores bot messages. The live test uses the existing bot
without adding a production test command or backdoor.

```text
explicit live pytest
    |
    +-> starts production coordinator factories
    +-> starts real OpenCode coordinator sandbox
    +-> starts ingress and ngrok
    +-> injects one-use E2E actor policy for PROBE_ID
    |
    +-> existing bot posts root with client_msg_id=PROBE_ID
            |
            v
       real Slack event -> real coordinator -> real OpenCode
            |
            v
       coordinator reply in real Slack thread
```

The one-use E2E actor policy is injected only by test composition. It accepts an
own-bot root only when its `client_msg_id` exactly matches the pre-armed probe
ID. Production policy has no environment flag, message prefix, route, or branch
that accepts bot work. Coordinator replies therefore remain ignored and cannot
loop.

Place the explicit test outside default discovery:

```text
bin/ocint/tests/live/ocint/daemon/coordinator/test_slack.py
```

It is not a production `slack-events-smoke` subcommand.

### Live Test Steps

1. Fail fast unless ports `8733`, `4098`, and the static ngrok domain are free.
2. Use the existing shared daemon database with a unique probe ID; never delete
   or recreate the database.
3. Start production coordinator composition with the one-use actor policy.
4. Start the real coordinator OpenCode server and verify exact version/health.
5. Start ngrok for the configured static URL.
6. Post a root to `C0955FD2FK4` using the existing bot token and probe ID.
7. Ask the coordinator to echo the probe ID and identify `dotfiles` from its
   repository catalogue.
8. Wait for the real signed Slack event to appear in durable state.
9. Assert one coordinator conversation and turn contain a real OpenCode session
   ID and assistant message ID.
10. Poll real Slack replies and assert the original thread contains the probe ID
    and `dotfiles` in the coordinator answer.
11. Assert no new task, job, worktree, Git operation, or GitHub publication was
    created for the probe.
12. Stop only ingress, ngrok, and OpenCode processes started by the test. Keep
    the marked Slack thread and database rows as evidence.

This proves the full path without waiting for a human Slack message.

## Deterministic Test Coverage

The live LLM test proves real integration but does not replace deterministic
tests.

### Unit

- authorization and bot filtering;
- provider-neutral message construction;
- deterministic session identity and prompts;
- response chunking, Unicode boundaries, and exact reconstruction;
- delivery scheduling and safe error text;
- coordinator repository claims and state transitions;
- generated workspace contents, permissions, and secret/path exclusion.

### Integration

- raw-body Slack HMAC and case-insensitive headers;
- timestamp freshness and body limits without `Content-Length`;
- URL verification and workspace checks;
- durable-before-ack and database-failure 5xx;
- event/message deduplication;
- Slack root/reply JSON, `client_msg_id`, reply lookup, and HTTP 429;
- OpenCode assistant ID/text extraction and recovery states;
- serialized migrations and concurrent engines against one SQLite file;
- coordinator/ngrok systemd rendering and credential isolation.

### Local E2E

Use fake Slack and fake OpenCode adapters with the real coordinator service and
temporary schema to verify:

- root then follow-up reuse one OpenCode session;
- duplicate Slack retries create one turn and reply;
- restart after prompt submission does not resubmit;
- uncertain Slack delivery is recovered without duplication;
- an 8,000+ character response produces ordered chunks;
- 429 during a middle chunk resumes correctly;
- bot reply events do not recurse;
- no task/job/execution dependency is invoked.

Tests follow GIVEN/WHEN/THEN and keep one canonical module per production module
at each test layer.

## Acceptance Criteria

### Transport And Security

- Slack can reach only `POST /slack/events` through ngrok.
- Every accepted callback has a valid fresh Slack signature.
- Events are durable before `200`; OpenCode and Slack replies happen later.
- OpenCode and daemon control APIs remain private.
- Slack, ngrok, GitHub, API, and SSH credentials are absent from coordinator
  OpenCode environment and workspace.

### Conversation

- An authorized Slack root creates one coordinator conversation and OpenCode
  session.
- Thread replies reuse that session and preserve order.
- The coordinator is the only Slack-facing agent.
- Bot replies cannot create recursive turns.
- The coordinator can read the repository catalogue and perform web research.
- Phase 1 cannot trigger repository OpenCode, tasks, jobs, Git, or publication.

### Persistence And Reliability

- One existing `daemon.sqlite` file and one migration chain serve both processes.
- Database management remains shared infrastructure; domain repositories retain
  their own state rules.
- Concurrent process access is covered by WAL, short transactions, uniqueness,
  busy timeout, and serialized migration.
- Slack retries do not duplicate prompts or replies.
- Restart resumes incomplete OpenCode and Slack delivery work.
- Oversized responses are delivered completely as ordered chunks.
- No database file is deleted or recreated.

### Autonomous E2E

- Existing bot posts the probe without user intervention.
- Slack sends the real event through ngrok.
- Durable state proves the real coordinator OpenCode sandbox ran.
- OpenCode reads `dotfiles` from coordinator context.
- Slack receives the coordinator answer in the same thread.
- No task/job/repository execution is triggered.

## File Impact

### New Coordinator Package

- `bin/ocint/ocint/daemon/coordinator/__init__.py`
- `bin/ocint/ocint/daemon/coordinator/config.py`
- `bin/ocint/ocint/daemon/coordinator/models.py`
- `bin/ocint/ocint/daemon/coordinator/service.py`
- `bin/ocint/ocint/daemon/coordinator/repository.py`
- `bin/ocint/ocint/daemon/coordinator/workspace.py`
- `bin/ocint/ocint/daemon/coordinator/run.py`

### Existing Production

- `daemon/db/connection.py`: serialized migration lock.
- `daemon/db/schema.py`: coordinator tables.
- `daemon/db/migrations/versions/`: one additive coordinator revision.
- `daemon/cli.py`: coordinator composition; remove Slack polling composition.
- `daemon/config.py`: aggregate coordinator config and environment settings.
- `daemon/opencode/config.py`, `service.py`, `__init__.py`: exact version and
  response-bearing completion.
- `daemon/slack/config.py`, `models.py`, `client.py`, `service.py`, `__init__.py`:
  event and delivery adapter responsibilities.
- New `daemon/slack/events.py`: signed ingress.
- `daemon/lch/systemd.py`, `setup.py`, `service.py`, `doctor.py`, `cli.py`: new
  units, workspace provisioning, diagnostics, and operations.
- `bin/ocint/tach.toml`: coordinator dependency boundaries.
- `bin/ocint/config/opencode.coordinator.json`: restricted coordinator policy.
- `bin/ocint/config/daemon.example.toml`: coordinator configuration.
- `bin/ocint/config/daemon.env.example`: Slack/ngrok environment documentation.
- `bin/ocint/config/slack-app-manifest.yaml`: `message.groups` subscription.

### Tests

- Mirror coordinator modules under unit/integration test paths.
- Add canonical Slack events integration tests.
- Extend canonical Slack client, OpenCode service, DB, config, LCH, and
  architecture tests.
- Add local coordinator E2E tests.
- Add explicit live Slack/ngrok/OpenCode test outside default discovery.

### Documentation

- Architecture: shared database, dual input mechanisms, process and sandbox
  diagrams, state and recovery.
- Configuration: coordinator TOML, catalogue, Slack Events setup, environment.
- Security: signatures, credential boundaries, OpenCode limitations.
- Operations: coordinator/ngrok units, diagnostics, restart, E2E invocation.
- ngrok: use `daemon.env`, static URL, dedicated service, no package `.env`.
- Workflow/indexes: coordinator conversation and Phase 1 exclusions.

## Implementation Sequence

1. Record worktree state and preserve unrelated/user edits.
2. Add failing architecture and local E2E tests proving coordinator isolation and
   Slack-to-coordinator behavior without jobs.
3. Tidy database migration locking in `daemon/db` and verify concurrent startup.
4. Tidy OpenCode response extraction and update the exact `1.18.15` pin; run
   existing job regression tests.
5. Add coordinator config/models and generated context workspace/policy.
6. Add coordinator tables to the shared schema/migration chain and implement
   repository transactions/recovery.
7. Add signed Slack ingress, normalized messages, and durable-before-ack.
8. Add coordinator worker and one-thread/one-session OpenCode conversation.
9. Add full response persistence, chunking, rate-aware Slack delivery, and
   uncertain-delivery recovery.
10. Remove Slack polling from timer-daemon composition while preserving old data.
11. Add standalone coordinator command and bounded startup/shutdown.
12. Add coordinator and ngrok systemd lifecycle and diagnostics.
13. Update examples, Slack manifest, and documentation.
14. Run focused tests, full checks, and existing GitHub/job regression tests.
15. Stop manually running probe/ngrok processes and run the autonomous live E2E.
16. Review durable rows and the real Slack thread before declaring Phase 1 done.

## Verification

Focused:

```bash
uv run --directory /home/vikram_orbio_earth/personal/dotfiles-wt \
  --package ocint --frozen pytest \
  bin/ocint/tests/unit/ocint/daemon/coordinator \
  bin/ocint/tests/integration/ocint/daemon/coordinator \
  bin/ocint/tests/integration/ocint/daemon/slack/test_events.py \
  bin/ocint/tests/integration/ocint/daemon/slack/test_client.py \
  bin/ocint/tests/integration/ocint/daemon/opencode/test_service.py \
  bin/ocint/tests/e2e/ocint/daemon/coordinator
```

Database, lifecycle, and architecture:

```bash
uv run --directory /home/vikram_orbio_earth/personal/dotfiles-wt \
  --package ocint --frozen pytest \
  bin/ocint/tests/integration/ocint/daemon/test_db.py \
  bin/ocint/tests/unit/ocint/daemon/lch \
  bin/ocint/tests/architecture/test_daemon_architecture.py
```

Full:

```bash
just --justfile bin/ocint/justfile test
just --justfile bin/ocint/justfile check
just --justfile bin/ocint/justfile smoke-daemon
```

Autonomous live E2E:

```bash
set -a
. "$HOME/.config/ocint/daemon.env"
set +a
uv run --directory /home/vikram_orbio_earth/personal/dotfiles-wt \
  --package ocint --frozen pytest -s \
  bin/ocint/tests/live/ocint/daemon/coordinator/test_slack.py
```

## Rollout And Rollback

Rollout:

1. Apply the shared additive migration without starting the coordinator worker.
2. Generate and inspect coordinator context and OpenCode policy.
3. Verify the existing GitHub timer daemon after Slack polling is disconnected.
4. Start coordinator locally and verify database/OpenCode health.
5. Start coordinator systemd service.
6. Start ngrok service against the already verified static domain.
7. Run the autonomous E2E in `C0955FD2FK4`.
8. Verify restart recovery before normal use.

Rollback:

1. Stop and disable coordinator/ngrok units.
2. Disable Slack Event Subscriptions manually only for prolonged rollback.
3. Preserve shared database and all coordinator rows.
4. Preserve workspace, OpenCode data, environment credentials, and Slack
   messages.
5. Keep GitHub timer daemon operational.

No rollback or test deletes a `.sqlite` or `.db` file.

## Research Basis

- Slack Events API acknowledgment, retry, and asynchronous-processing contract:
  <https://docs.slack.dev/apis/events-api/>
- Slack raw-body HMAC and replay protection:
  <https://docs.slack.dev/authentication/verifying-requests-from-slack/>
- Private-channel `message.groups` event and `groups:history` scope:
  <https://docs.slack.dev/reference/events/message.groups/>
- Slack message length and posting-rate guidance:
  <https://docs.slack.dev/reference/methods/chat.postMessage>
- OpenCode server session/message/status/SSE APIs and basic authentication:
  <https://opencode.ai/docs/server/>
