# Slack Coordinator Phase 1 Plan

## Outcome

Phase 1 connects Slack to one always-running coordinator OpenCode sandbox.

```text
Slack public-channel thread
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

The acceptance test is fully autonomous. An authorized test user posts a marked
message with the User OAuth Token issued through the separate `ocint E2E actor`
app. Slack delivers an app-authored `message.channels` event carrying the
authorized user ID through ngrok. A test-only exact-probe classifier accepts only
that event, the real coordinator OpenCode sandbox runs, and the production bot
posts the answer in the Slack thread. No person manually posts or clicks during
the test. Production classification still ignores every bot/app-authored event.

This plan supersedes the earlier Slack Events plan and the previous version of
this plan. External viability is proven with persisted probe evidence: Slack
verified the static ngrok URL, and the temporary signed receiver recorded both a
human UI message and an xoxp app-authored message as valid `message.channels`
callbacks with HTTP `200`. The earlier `message.groups` subscription was wrong
because `C0955FD2FK4` is public.

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
- A reply delivered before its root is stored without creating OpenCode work.
  Its conversation remains `awaiting_root` until the authorized root arrives.
- When the root arrives, the conversation becomes `active` and all stored
  messages become turns in exact Slack timestamp order.
- Orphan replies that never receive a root are expired after the configured
  retention period without OpenCode work.
- Turns are processed in source-message order. Slack timestamps are parsed into
  an exact integer ordering key without floating-point conversion; immutable
  provider message identity is the tie-breaker.
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

Phase 1 enforces its single-worker rule with one daemon-owned coordinator
runtime lock. A second coordinator process fails before starting ingress or
OpenCode. Database transitions still use conditional updates, but no lease or
distributed-worker protocol is added until coordinator concurrency is required.

Database migration is a shared database-management responsibility. Protect
migrations with one daemon-owned filesystem lock so the timer and coordinator
cannot run Alembic concurrently. Each process may call migration at startup, but
only one performs it at a time and all workers start after the lock is released.

## Tidy, First

Perform only the preparation required to make the implemented behavior readable,
observable, and safe before adding more behavior:

1. **Channel event contract:** represent public `channel` and private `group`
   message payloads as a normal Pydantic typed union, without a discriminator.
   Deploy only `message.channels`/`channels:history` in Phase 1 and leave a code
   FIXME at the private variant because `message.groups`/`groups:history`
   deployment is not implemented. Persist sanitized fixtures from both proven
   public-channel callback shapes before changing translation tests.
2. **Coordinator lifecycle:** move runtime lock ownership, OpenCode start/stop,
   worker/ingress supervision, and bounded shutdown out of `daemon/cli.py` and
   into the coordinator workflow facade. CLI remains the composition root but
   delegates lifecycle to one exported operation.
3. **Slack ingress:** replace the nested 60-line route closure with a cohesive
   ingress owner in `daemon/slack/events.py`. It owns bounded body reading,
   authentication, parsing, normalization, durable dispatch, acknowledgement,
   and safe ingress logs.
4. **Live harness:** move the live test under the normal `tests/` hierarchy,
   gate it with a strict pytest marker, and reuse the production coordinator
   application lifecycle instead of duplicating 400 lines of setup and cleanup.
5. **Observability:** add safe structured logs at ingress, workflow, delivery,
   retry, and lifecycle checkpoints before further rollout. Never log message
   text, prompts, responses, raw envelopes, headers, signatures, or credentials.
6. **Keep atomic work atomic:** do not split `CoordinatorRepository.ingest`,
   migration locking, LCH discovery, or doctor aggregation only because they are
   long. Their current transaction/security boundaries are cohesive.
7. **Bound ordered-turn recovery:** configure a positive `max_turn_retries`
   budget, defaulting to three retries after the initial attempt. Retryable
   OpenCode errors and inactive incomplete prompt observations consume that
   budget without resubmission. Exhaustion persists and delivers the existing
   safe failure response so the next ordered turn can run. Slack delivery
   retries do not consume this budget; they remain unbounded and preserve the
   response already persisted for delivery.
8. **Out-of-plan production restart lifecycle:** make the coordinator facade the
   sole process-signal owner from before OpenCode startup through final close. A
   signal during startup cancels and closes OpenCode as an expected normal exit;
   startup failure remains an error. Once running, unexpected child, worker, or
   ingress completion takes precedence over a concurrent shutdown request.
   Bounded worker/ingress shutdown precedes OpenCode close and prior handlers are
   restored. Only coordinator ingress uses signal-free Uvicorn; the generic
   daemon retains normal Uvicorn signal ownership. Keep `KillMode=mixed` so the
   initial stop signal targets the main process.

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
  - models.py       normalized input, conversation, turn, delivery vocabulary
  - service.py      authorization, prompt, response chunking
  - repository.py   coordinator persistence operations
  - workspace.py    generated context workspace
  - run.py          application lifecycle, worker, recovery, supervision
  - __init__.py     supported facade and narrow adapter protocols

daemon/slack/
  - config.py       workspace/channel authorization
  - models.py       Events API and Web API DTOs
  - events.py       cohesive signed HTTP ingress and acknowledgement owner
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
  - resolve config/secrets, construct adapters, call feature workflow
```

Dependency direction:

```text
Slack adapter -> coordinator-owned input and delivery ports
                         |
                         +-> OpenCode facade
                         `-> daemon/db

CLI composition root -> coordinator + Slack + OpenCode

coordinator -X-> slack
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
this explicit architecture change. The existing execution repository registry
remains authoritative. Add safe descriptive metadata to those entries and
generate `repositories.json` by projecting only name, description,
`github_repository`, and `default_branch`. Do not create a second coordinator
repository registry.

The following is an additive excerpt; all existing required daemon, GitHub, Git,
job OpenCode, mirror, worktree, and repository fields remain in the complete
example TOML:

```toml
database_path = "~/.local/state/ocint/daemon.sqlite"

[coordinator]
workspace_root = "~/.local/share/ocint/coordinator"
turn_timeout_seconds = 1800
shutdown_timeout_seconds = 30
max_turn_retries = 3
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
expected_version = "1.18.16"
executable = "/path/to/opencode"
config_file = "~/.config/ocint/coordinator-opencode-xdg/opencode/opencode.json"
xdg_config_home = "~/.config/ocint/coordinator-opencode-xdg"
xdg_data_home = "~/.local/share/ocint/coordinator-opencode-data"
```

Each existing `[[repositories]]` entry gains a required safe `description`
field. Coordinator workspace generation receives only the safe projection, not
the complete execution configuration.

Validation rules:

- The coordinator workspace differs from mirrors and worktrees.
- Coordinator and job OpenCode ports differ and are loopback-only.
- Ingress is loopback-only and differs from control API port `8732`.
- Existing repository names remain unique and descriptions are non-empty.
- Authorized-user sets are non-empty.
- Inbound channel events parse through a non-discriminated typed union whose
  variants require `channel_type = "channel"` or `channel_type = "group"`.
- Phase 1 deployment configures only public Slack channels; private-channel
  subscription and OAuth scope deployment are not implemented.
- Slack workspace matches `auth.test`.
- Response chunk size leaves room below Slack's 4,000-character recommendation.
- Timeouts, body limits, and delivery intervals are positive.
- The turn retry budget is positive. It counts retry schedules after the initial
  attempt: `3` means at most four OpenCode processing attempts, not three total
  attempts.

Production credentials remain in the existing mode-0600 daemon environment
file:

```text
OCINT_DAEMON_SLACK_BOT_TOKEN
OCINT_DAEMON_SLACK_SIGNING_SECRET
OCINT_NGROK_URL
```

The live E2E actor token is intentionally separate in the mode-0600
`~/.config/ocint/live-e2e.env` file:

```text
OCINT_E2E_SLACK_ACTOR_USER_TOKEN
```

The coordinator systemd units load only `daemon.env`. They never load the live
test credential. No package `.env` file or token in tracked configuration is
used.

Slack channel visibility determines both subscription and OAuth scope:

| Channel | Event | History scope | Phase 1 |
| --- | --- | --- | --- |
| Public | `message.channels` | `channels:history` | Supported |
| Private | `message.groups` | `groups:history` | Documented, not configured |

Do not request both scopes speculatively. Supporting a private channel later
requires an explicit configuration/model change, manifest update, and live
contract test.

### External API Contract Prerequisite

The host-observed OpenCode version is `1.18.16`. The final top-stack E2E
live-contract verified the real OpenCode `1.18.16` server and configured Slack
workspace on 2026-08-10:

1. Verify whether prompt submission accepts a caller-selected deterministic user
   `messageID`.
2. Verify assistant messages expose stable IDs, the corresponding user
   `parentID`, terminal status, ordered text parts, and distinguishable
   interrupted state.
3. Verify session/message/status/SSE behavior and capture sanitized JSON fixtures
   for deterministic integration tests.
4. Verify `conversations.replies` returns `client_msg_id` for bot-authored posts,
   including paginated thread history.
5. Verify what a repeated `chat.postMessage` with the same UUID
   `client_msg_id` does: deduplicates, returns a recognizable error, or creates a
   second message.
6. Record the confirmed contracts in the OpenCode and Slack adapter tests. If a
   required correlation or recovery contract is unavailable, stop and revise
   this plan before creating the migration.
7. Update the exact supported pin to `1.18.16` for both OpenCode runtimes, keep
   exact startup checks, and re-run existing PR-job recovery tests.

## OpenCode Policy And Workspace

LCH creates private coordinator directories and provisions policy and auth only.
Coordinator startup is the single owner that atomically generates `AGENTS.md`
and `repositories.json` from its final validated repository projection. Doctor
may report this context as pending before first coordinator startup. Generated
directories use mode `0700` and files use mode `0600`.

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

Expose this file through a package resource/symlink beside the existing daemon
OpenCode policy, include it in wheel and sdist builds, and give LCH a distinct
typed coordinator-policy loader. Installed LCH must not depend on a source-tree
relative `config/` path.

The OpenCode child receives only isolated HOME/XDG paths, OpenCode provider
authentication, its ephemeral HTTP basic-auth values, PATH, and locale. It does
not receive Slack, ngrok, GitHub, daemon API, SSH, or Git credentials.
It runs without `--print-logs`, and child stdout/stderr are discarded so prompts,
responses, and provider diagnostics cannot enter the coordinator journal.

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
8. Convert supported public `event_callback` messages into normalized
   conversation messages. Parse public `channel` and private `group` payloads
   through a normal Pydantic typed union, without a discriminator, but durably
   ignore private payloads before authorization. Phase 1 deploys only
   `message.channels`; private translation, subscription, and scope deployment
   remain an explicit FIXME.
9. In one repository transaction, insert/deduplicate the provider event, insert
   the logical message, create or update the conversation, and create all newly
   eligible turns. Unsupported events commit only their ignored disposition.
10. Commit before acknowledging. Worker wakeup is only a latency optimization;
    the worker always queries durable ready state after startup and wakeup.
11. Wake the worker and return `200` without calling OpenCode or Slack Web API.

Slack requires a 2xx within three seconds. A database failure returns 5xx so
Slack retries. Duplicate event or message identity returns `200` without another
turn. Reuse of a provider event ID with a different immutable fingerprint is
logged as an identity conflict and never creates work.

If durable dispatch exceeds the configured processing budget, return `503`
immediately. Do not wait for the shielded thread before responding and do not
wake the worker from the timed-out request. Observe and safely log the eventual
background result; a late commit is recovered by durable-state scanning and the
Slack retry deduplicates it.

Do not store raw envelopes, signatures, deprecated verification tokens,
authorization arrays, or request headers.

## Observability

The existing private rotating `daemon.log` remains the production log. Add
structured events in the owning modules rather than enabling generic Uvicorn
access logs or ngrok inspection in production.

```text
signed callback
      |
      +-> ingress authenticated / rejected
      +-> event committed / deduplicated / ignored / timed out
      +-> turn claimed / retried / completed
      +-> OpenCode observed / submitted / completed
      `-> Slack chunk intended / recovered / posted / retried
```

Required correlation fields where available:

- `workspace`, `channel`, `thread`, `event`, and `message` at ingress;
- `conversation`, `turn`, `state`, `retry_count`, and `error_type` in workflow;
- `session` and managed user/assistant message IDs for OpenCode correlation;
- `turn`, `chunk_index`, `client_message`, and `provider_message` for delivery;
- `pid`, `host`, `port`, `exit_status`, and shutdown outcome for lifecycle.

Never log Slack text, managed prompts, assistant responses, raw request bodies,
headers, signatures, tokens, passwords, complete environments, ngrok URLs, or
provider credentials. Rejections log only reason/status and safe request size.

The live run configures a separate mode-0600
`~/.local/state/ocint/live-e2e.log` and captures harness-owned ngrok output in a
mode-0600 `live-e2e-ngrok.log`. Both include the unique probe ID as a correlation
field, but no credentials or raw callback payload. Production ngrok inspection
remains disabled.

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
  unique(provider, workspace_id, channel_id, thread_id, message_id)

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
  source_order_at
  source_order_tiebreaker
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
oldest ready turn with an atomic transaction. Convert provider timestamps to one
canonical UTC ordering value at the provider boundary and use immutable provider
message identity as the tie-breaker. A turn is claimable only when its
conversation has no earlier non-terminal turn, including an earlier turn waiting
for retry. This prevents a deferred first turn from being overtaken by a later
Slack reply. Existing task/job claims remain independent.

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
- Prompt present but inactive/incomplete: schedule observation retry without
  adding a second managed user message, until the configured turn retry budget
  is exhausted.
- Prompt with a persisted terminal error: deliver the safe failure response
  without resubmission. A retryable persisted error schedules observation retry
  without resubmission until that same budget is exhausted.
- Budget exhaustion persists and delivers the safe failure response, terminally
  completes the failed turn, and makes the next ordered turn eligible. The
  budget counts retries after the initial attempt; a value of three permits one
  initial attempt and three retries.
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
- OpenCode transient failure: retain the turn and retry with bounded backoff up
  to the configured retry budget, then persist and deliver the safe failure.
- OpenCode terminal failure or timeout: persist and deliver one safe coordinator
  failure response without provider details.
- Slack network/5xx failure: retain delivery and the persisted response for
  unbounded retry; the OpenCode retry budget does not apply.
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
- uses `KillMode=mixed` so SIGTERM first reaches the lifecycle-owning main
  process and systemd may clean up the cgroup only after its stop timeout

A coordinator signal handler is installed before OpenCode startup. A requested
shutdown during startup cancels and closes OpenCode, restores the handler, and
maps to normal process exit. Startup failure still closes OpenCode and fails the
service. After startup, unexpected worker, ingress, or child completion takes
precedence over a concurrent requested shutdown.

A graceful restart logs `Coordinator bounded shutdown started` and completed,
then `Coordinator OpenCode shutdown started` and completed. It does not report
the managed OpenCode child as an unexpected exit.

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
Initial setup leaves coordinator units disabled. Subsequent setup/apply preserves
their existing enablement and reports the actual unit-file states.

Uninstall removes units but preserves the shared database, coordinator rows,
workspace context, OpenCode data, credentials, and Slack messages.

## Autonomous Live E2E

The production policy accepts configured human users and ignores bot messages.
The live test uses an authorized test user's xoxp token issued through the
separate `ocint E2E actor` app, without adding a production test command or
backdoor. The production bot remains the delivery client.

```text
explicit live pytest
    |
    +-> starts production coordinator factories
    +-> starts real OpenCode coordinator sandbox
    +-> starts ingress and ngrok
    +-> authenticates production bot + authorized test user
    +-> arms one exact test-only xoxp event policy
    |
    +-> test user's xoxp client posts root with client_msg_id=PROBE_ID
             |
             v
        app-authored message.channels event -> real coordinator -> real OpenCode
             |
             v
        production bot reply in real Slack thread
```

The real callback probe established two distinct shapes:

- Slack UI message: authorized `user`, no `bot_id`/`app_id`;
- xoxp `chat.postMessage`: the same authorized `user` plus app-owned `bot_id`,
  `app_id`, and the caller `client_msg_id`.

Production uses its normal classifier, so the second shape remains `BOT` and is
ignored. The live harness injects a one-use classifier only in test composition.
It accepts one public-channel root when workspace, channel, authorized user,
exact UUID `client_msg_id`, and exact prompt all match, and when `bot_id` and
`app_id` are present. Slack retries of that exact event remain acceptable for
repository deduplication. No environment switch, route, prefix, or production
branch enables this policy. Production bot replies have a different app/user and
client ID and remain ignored.

Keep the live test in the canonical test hierarchy:

```text
bin/ocint/tests/live/ocint/daemon/coordinator/test_slack.py
```

Mark it `@pytest.mark.live`. Default pytest options use strict markers and
`-m "not live"`, so normal `pytest` and `just test` discover and deselect it.
Running the file path without `-m live` also remains safe. It is not a production
`slack-events-smoke` command.

### E2E Actor Setup

The separate app named `ocint E2E actor` was created from
`config/slack-e2e-actor-manifest.yaml`. It grants user OAuth `chat:write` and was
reinstalled so the configured authorized user has an xoxp User OAuth Token.
Slack still marks API-authored posts with that app's `bot_id`/`app_id`; this is
why the exact test-only classifier is required. The app has no event
subscriptions, Socket Mode, or interactivity. The authorized user belongs to the
public E2E channel. Store only the User OAuth Token as
`OCINT_E2E_SLACK_ACTOR_USER_TOKEN` in mode-0600
`~/.config/ocint/live-e2e.env`. Do not add that assignment to `daemon.env` or a
systemd unit.

### Live Test Steps

1. Fail fast unless production coordinator/ngrok units are inactive and ports
   `8733` and `4098` are free. Make one bounded sanitized request to the
   configured callback endpoint and proceed only when a typed classifier sees
   ngrok's `404`/`ERR_NGROK_3200` offline-domain response. Treat every active
   backend/tunnel or ambiguous/network response as failure without logging URL,
   body, headers, or credentials and without using the ngrok inspector.
2. Source production credentials from mode-0600 `daemon.env` and the test user
   token from separate mode-0600 `live-e2e.env`; never load the test token
   through systemd or print it.
3. Require the actor credential to be xoxp, authenticate both clients with
   `auth.test`, require the configured workspace, and require the actor user to
   appear in the channel's `authorized_users`.
4. Use the existing shared daemon database with a unique probe ID; never delete
   or recreate the database.
5. Start the exported production coordinator application lifecycle with normal
   configured-channel authorization and the exact test-only xoxp event
   classifier, while keeping the production bot as the delivery client.
6. Start the real coordinator OpenCode server and verify exact version/health.
7. Start ngrok for the preflighted static URL.
8. Post a root to the configured public channel using the authorized user's
   Slack client and the probe ID as `client_msg_id`.
9. Ask the coordinator to echo the probe ID and identify `dotfiles` from its
   repository catalogue.
10. Wait up to 90 seconds for the real signed Slack event to appear in durable
    state, reporting callback status codes without request bodies or secrets.
11. Resolve the conversation and turn through the probe event/client-message ID,
   then assert those probe-scoped rows contain a real OpenCode session ID and
   assistant message ID. Do not assert global row counts in the shared database.
12. Poll real Slack replies with the production bot and assert the original
    thread contains the probe ID and `dotfiles` in the coordinator answer.
13. Assert no new task, job, worktree, Git operation, or GitHub publication was
    created for the probe.
14. Stop only ingress, ngrok, OpenCode, and Slack clients started by the test. Keep
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
- non-discriminated typed-union parsing and translation for public `channel` and
  private `group` message payloads, with public-only deployment coverage;
- durable-before-ack and database-failure 5xx;
- immediate `503` at the processing deadline without waiting for a blocked
  ingest thread or waking the worker;
- event/message deduplication;
- Slack root/reply JSON, `client_msg_id`, reply lookup, and HTTP 429;
- OpenCode assistant ID/text extraction and recovery states;
- serialized migrations and concurrent engines against one SQLite file;
- simultaneous migrations from two separate processes using the same canonical
  database-derived lock;
- coordinator/ngrok systemd rendering and credential isolation.

### Local E2E

Use fake Slack and fake OpenCode adapters with the real coordinator service and
temporary schema to verify:

- root then follow-up reuse one OpenCode session;
- duplicate Slack retries create one turn and reply;
- restart after prompt submission does not resubmit;
- repeated retryable and interrupted prompt recovery exhausts the configured
  budget, delivers the safe failure once, and releases the next ordered turn;
- uncertain Slack delivery is recovered without duplication;
- Slack delivery can retry beyond the OpenCode budget without replacing the
  persisted response;
- an 8,000+ character response produces ordered chunks;
- 429 during a middle chunk resumes correctly;
- bot reply events do not recurse;
- no task/job/execution dependency is invoked.

Tests follow GIVEN/WHEN/THEN and keep one canonical module per production module
at each test layer. Logging tests assert safe correlation fields and prohibited
field absence, not incidental rendered log prose.

## Acceptance Criteria

### Transport And Security

- Slack can reach only `POST /slack/events` through ngrok.
- Every accepted callback has a valid fresh Slack signature.
- The configured public channel uses `message.channels` and `channels:history`;
  private-channel permissions are not requested.
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
- Exhausted OpenCode retries terminally fail one turn with the safe response so
  a later ordered turn is not blocked forever; Slack delivery remains unbounded.
- Oversized responses are delivered completely as ordered chunks.
- No database file is deleted or recreated.

### Autonomous E2E

- The authorized test user's xoxp client posts the probe without manual user
  intervention. Slack delivers the observed app-authored `message.channels`
  shape with authorized user, app/bot IDs, and exact client message ID.
- The User OAuth Token stays in `live-e2e.env`, outside daemon systemd
  configuration.
- `auth.test` proves the token belongs to the configured workspace and identifies
  a user authorized for the configured channel.
- The test-only classifier accepts only the exact prearmed xoxp event; production
  classification continues ignoring all app/bot events.
- Slack sends the signed event through ngrok.
- Durable state proves the real coordinator OpenCode sandbox ran.
- OpenCode reads `dotfiles` from coordinator context.
- The production bot delivers the coordinator answer in the same thread and its
  own events remain ignored.
- No task/job/repository execution is triggered.

### Maintainability And Operations

- `daemon/cli.py` resolves configuration and constructs adapters but does not own
  coordinator process supervision, runtime locks, OpenCode lifecycle, or task
  cancellation.
- `daemon/slack/events.py` has one cohesive ingress owner; the FastAPI route is a
  thin delegation.
- The live test reuses the production application lifecycle and contains only
  preflight, probe submission, evidence assertions, and test-specific cleanup.
- Atomic repository and security-validation operations are not fragmented merely
  to reduce line count.
- Production logs expose enough safe correlation IDs to trace callback, turn,
  OpenCode, delivery, retry, and shutdown without logging content or secrets.

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
- `daemon/db/migrations/versions/`: the additive coordinator revision followed
  by a second migration completing thread-aware message identity.
- `daemon/cli.py`: thin coordinator composition; remove lifecycle supervision and
  Slack polling composition.
- `daemon/config.py`: aggregate coordinator config and environment settings.
- `daemon/opencode/config.py`, `service.py`, `__init__.py`: exact version and
  response-bearing completion.
- `daemon/slack/config.py`, `models.py`, `client.py`, `service.py`, `__init__.py`:
  event and delivery adapter responsibilities.
- New `daemon/slack/events.py`: cohesive signed ingress owner, deadline handling,
  and safe structured callback logs.
- `daemon/lch/systemd.py`, `setup.py`, `service.py`, `doctor.py`, `cli.py`: new
  units, workspace provisioning, diagnostics, and operations.
- `bin/ocint/tach.toml`: coordinator dependency boundaries.
- `bin/ocint/config/opencode.coordinator.json`: restricted coordinator policy.
- `bin/ocint/config/daemon.example.toml`: coordinator configuration.
- `bin/ocint/config/daemon.env.example`: Slack/ngrok environment documentation.
- `bin/ocint/config/slack-app-manifest.yaml`: public-channel
  `message.channels` subscription and `channels:history` scope.
- `bin/ocint/config/slack-e2e-actor-manifest.yaml`: test-user OAuth `chat:write` actor app.
- `bin/ocint/config/live-e2e.env.example`: isolated live actor credential example.
- `bin/ocint/justfile`: include coordinator tables in the exact daemon schema
  smoke assertion.
- `bin/ocint/pyproject.toml`: register strict `live` marker and deselect it by
  default while keeping all tests under `tests/`.

### Tests

- Mirror coordinator modules under unit/integration test paths.
- Add canonical Slack events integration tests.
- Extend canonical Slack client, OpenCode service, DB, config, LCH, and
  architecture tests.
- Add local coordinator E2E tests.
- Add the explicit live Slack/ngrok/OpenCode test under `tests/live/`, marked
  `live` and deselected by default.
- Add sanitized real callback fixtures for public human UI and xoxp app-authored
  `message.channels` events.

### Documentation

- Architecture: shared database, dual input mechanisms, process and sandbox
  diagrams, state and recovery.
- Configuration: coordinator TOML, catalogue, Slack Events setup, environment.
- Security: signatures, credential boundaries, OpenCode limitations.
- Slack channel visibility: public/private event names, OAuth scopes, channel
  type fields, and current public-only support.
- Operations: coordinator/ngrok units, diagnostics, restart, E2E invocation.
- ngrok: use `daemon.env`, static URL, dedicated service, and source the separate
  `live-e2e.env` only for the explicit harness; no package `.env`.
- Workflow/indexes: coordinator conversation and Phase 1 exclusions.

## Implementation Sequence

1. Record worktree state and preserve unrelated/user edits.
2. Persist sanitized fixtures from the proven `message.channels` human and xoxp
   callbacks; update Slack contract tests before production translation.
3. Model public `channel` and private `group` messages as a normal Pydantic typed
   union without a discriminator. Replace deployed
   `message.groups`/`groups:history` with `message.channels`/`channels:history` in
   the manifest, access validation, examples, doctor, and documentation. Keep
   private parsing support, add a code FIXME that private deployment is not
   implemented, and do not deploy its subscription or scope.
4. Tidy coordinator process lifecycle out of `daemon/cli.py` into an exported
   coordinator application context/workflow with injected delivery and generic
   ingress dependencies. Preserve `coordinator -X-> slack` in Tach.
5. Tidy `daemon/slack/events.py` into a cohesive ingress owner. Correct timeout
   semantics so `503` returns within budget without awaiting the blocked thread.
6. Add safe structured logs across ingress, runtime, OpenCode correlation,
   delivery, retries, child exit, and bounded shutdown. Extend sensitive-field
   architecture checks.
7. Remove unused coordinator config types or wire them into the supported
   application request; do not retain parallel unused policy models.
8. Move the live test to `tests/live/`, register the strict marker/default
   deselection, and reuse the production application context to remove duplicated
   lifecycle code.
9. Update actor setup and live policy for the observed xoxp callback shape. Keep
   the policy test-only and exact-probe scoped.
10. Update public/private Slack permission documentation, operations, security,
    architecture diagrams, and implementation notes.
11. Run focused tests, all 600+ deterministic tests, static checks, architecture,
    schema smoke, package builds, and existing GitHub/job regressions.
12. Stop temporary probe/ngrok windows, confirm production units are inactive,
    and run the marker-gated autonomous live E2E in a newly created tmux window.
13. Review probe-scoped durable rows, safe live logs, ngrok log, and the real
    Slack thread.
14. Only after live E2E and independent review pass, enable coordinator/ngrok,
    verify restart recovery, commit, push, and open the PR.

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
  bin/ocint/tests/integration/ocint/daemon/test_run.py \
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
. "$HOME/.config/ocint/live-e2e.env"
set +a
uv run --directory /home/vikram_orbio_earth/personal/dotfiles-wt \
  --package ocint --frozen pytest -m live -s \
  bin/ocint/tests/live/ocint/daemon/coordinator/test_slack.py
```

## Rollout And Rollback

Rollout:

1. Apply setup and inspect coordinator OpenCode policy/auth without manually
   migrating the database.
2. Start the timer or coordinator to exercise serialized migration; coordinator
   startup atomically generates context from the final repository projection.
3. Verify the existing GitHub timer daemon after Slack polling is disconnected.
4. Keep production coordinator/ngrok units disabled and run the autonomous E2E
   harness in public channel `C0955FD2FK4`.
5. Inspect probe-scoped database evidence and mode-0600 live/ngrok logs, then stop
   only harness-owned processes.
6. Start coordinator systemd service.
7. Start ngrok service against the already verified static domain.
8. Verify production restart recovery before normal use.

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
- Public-channel `message.channels` event and `channels:history` scope:
  <https://docs.slack.dev/reference/events/message.channels/>
- Private-channel comparison (`message.groups`/`groups:history`), not configured
  in Phase 1: <https://docs.slack.dev/reference/events/message.groups/>
- Slack message length and posting-rate guidance:
  <https://docs.slack.dev/reference/methods/chat.postMessage>
- OpenCode server session/message/status/SSE APIs and basic authentication:
  <https://opencode.ai/docs/server/>
