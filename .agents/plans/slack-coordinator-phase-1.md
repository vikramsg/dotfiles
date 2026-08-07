# Slack Coordinator Phase 1 Plan

## Outcome

Phase 1 creates one always-on coordinator sandbox that can hold a conversation
with Slack through OpenCode.

```text
Slack private-channel thread
          |
          | signed Events API callback
          v
ngrok -> coordinator ingress on 127.0.0.1:8733
          |
          | durable turn
          v
coordinator sandbox
  - generated context workspace
  - repository catalogue
  - private OpenCode HTTP server
  - read and web-research tools
          |
          | final assistant response
          v
Slack reply in the original thread
```

The coordinator is the only agent that communicates with Slack. There is no
repository sandbox in Phase 1. The coordinator may explain that repository work
is needed, but it cannot trigger, edit, commit, push, or publish anything.

This plan supersedes `.agents/plans/slack-events-api-smoke.md`. The external
viability work from that plan is already complete: Slack has verified the
static ngrok URL, `message.groups` is subscribed, and the configured signing
secret has authenticated a real Slack request.

## Business Model

### Coordinator Sandbox

The coordinator sandbox is a generated context workspace, not a checkout of a
target repository:

```text
coordinator workspace
├── AGENTS.md
└── repositories.json
```

`AGENTS.md` defines the coordinator's role and Phase 1 limits.
`repositories.json` lists the repositories that may become execution targets in
later phases. Each entry contains a stable configured name, a human-readable
description, the GitHub repository identity, and the default branch. It contains
no credentials, local target-repository paths, author details, or SSH material.

The workspace is called a sandbox because OpenCode is constrained to that
directory and a restrictive tool policy. It is not an operating-system security
sandbox; the process still runs as the daemon user. Phase 1 reduces that risk by
denying shell execution, edits, and external-directory access and by giving the
OpenCode child a credential-minimal environment.

### Conversation

One physical Slack root thread maps to one OpenCode session:

```text
Slack root message -----> coordinator conversation -----> OpenCode session
Slack thread reply -----^                               |
                                                        v
                                                accumulated context
```

- An authorized human root creates the conversation and OpenCode session.
- Authorized human replies in that Slack thread become later turns in the same
  OpenCode session.
- Turns are processed in Slack message order, one at a time.
- Coordinator replies are posted to the Slack root thread.
- Bot replies, message edits, deletions, file-only events, unsupported subtypes,
  and messages outside configured channels are acknowledged and ignored.
- Unauthorized actors are acknowledged and ignored without invoking OpenCode or
  posting a response.

### Future Repository Delegation

Phase 2 will add a daemon-owned contract from the coordinator to a selected
repository sandbox:

```text
coordinator -> delegation policy/router -> repository sandbox -> result
     ^                                                      |
     `---------------- synthesized Slack response -----------'
```

Do not add that contract in Phase 1. There is not yet enough concrete behavior
to define its request, progress, cancellation, or result model. The coordinator
context should instead say that repository execution is unavailable and that it
must clearly identify the likely repository and objective when work is needed.
This preserves the seam without speculative code.

## Process Architecture

The current timer daemon is intentionally bounded and cannot own a continuously
available webhook. Phase 1 adds a separate process:

```text
ocint-daemon.timer
    `-> ocint-daemon.service (oneshot)
          `-> existing GitHub task/job/worktree flow

ocint-coordinator.service (always on)
    +-> FastAPI ingress: 127.0.0.1:8733
    +-> coordinator worker
    `-> OpenCode child: 127.0.0.1:4098

ocint-coordinator-ngrok.service (always on)
    `-> static public URL -> 127.0.0.1:8733
```

The coordinator service owns the lifespan of its OpenCode child. It starts the
private server, verifies its exact version, recovers durable turns, starts the
worker, then accepts Slack callbacks. During shutdown it stops accepting HTTP,
allows the active turn a bounded grace period, leaves unfinished checkpoints
recoverable, and closes OpenCode.

The ngrok service uses the configured `OCINT_NGROK_URL`, disables request
inspection, and forwards only to the dedicated ingress port. It never forwards
the daemon control API on `8732` or OpenCode on `4098`.

## Tidy, First

Make two small preparatory changes before adding coordinator behavior:

1. Extend the OpenCode facade with a response-bearing conversation operation.
   The current client can submit and wait but discards the assistant's identity
   and text. Add an immutable completion result containing the terminal
   assistant message ID and concatenated text parts. Preserve the existing PR
   job methods and behavior.
2. Separate Slack transport from polling workflow. Keep reusable Web API calls,
   typed wire payloads, rate-limit errors, and authentication in `slack/`.
   Remove Slack polling from timer-daemon composition before enabling inbound
   events, so one Slack message cannot enter both the legacy task flow and the
   coordinator flow.

Do not refactor GitHub, Git, task, or pull-request-job modules. The coordinator
must not depend on them.

## Module Ownership

```text
daemon/cli.py
  - Click composition roots
  - constructs concrete coordinator dependencies

daemon/coordinator/
  - config.py       coordinator-owned policy
  - models.py       conversation, turn, response, delivery vocabulary
  - service.py      authorization, prompts, response chunking
  - repository.py   durable conversation and delivery operations
  - workspace.py    generated context workspace
  - run.py          recovery, worker, service lifespan
  - db/             independent schema and migrations
  - __init__.py     supported facade

daemon/slack/
  - config.py       workspace and channel authorization
  - models.py       Slack Events and Web API DTOs
  - events.py       signed inbound HTTP adapter
  - client.py       Slack Web API adapter
  - service.py      provider translation and reply delivery
  - __init__.py     supported facade

daemon/opencode/
  - existing private HTTP/process adapter
  - response-bearing completion contract

daemon/lch/
  - coordinator and ngrok systemd lifecycle
  - diagnostics and setup
```

Dependency direction:

```text
Slack ingress -> coordinator contracts <- coordinator worker
                       |
                       +-> OpenCode conversation contract
                       `-> Slack delivery contract

coordinator -X-> tasks
coordinator -X-> pull_request_job
coordinator -X-> git
coordinator -X-> github
coordinator -X-> daemon control API
```

Enforce these boundaries with Tach. Do not add AST tests that duplicate Tach.

## Configuration

Replace the polling-oriented root `[slack]` configuration with coordinator-owned
configuration. Backward compatibility is not required because inbound Slack is
an explicit architecture replacement.

Illustrative shape:

```toml
[coordinator]
database_path = "~/.local/state/ocint/coordinator.sqlite"
workspace_root = "~/.local/share/ocint/coordinator-workspace"
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

- Coordinator database and workspace paths are distinct from daemon job state,
  mirrors, and worktrees.
- Ingress and both OpenCode ports are unique and loopback-only.
- Slack channel IDs are unique and actor allowlists are non-empty.
- Repository catalogue names are unique.
- Configured Slack workspace must match `auth.test`.
- Response chunk size stays below Slack's 4,000-character recommendation after
  adding chunk numbering.
- Request and lifecycle timeouts are positive and bounded.

Credentials stay in mode-0600 `$XDG_CONFIG_HOME/ocint/daemon.env`:

```text
OCINT_DAEMON_SLACK_BOT_TOKEN
OCINT_DAEMON_SLACK_SIGNING_SECRET
OCINT_NGROK_URL
```

The coordinator OpenCode password is generated in memory for each service
process. It is never persisted or passed in argv.

### OpenCode Version Prerequisite

The VM currently has OpenCode `1.18.15`, while existing daemon configuration is
hard-pinned to `1.17.20`. Resolve this before coordinator implementation:

1. Run the existing OpenCode HTTP integration suite against the `1.18.15`
   protocol shape.
2. Update the exact supported version pin to `1.18.15` for both runtimes.
3. Keep startup exact-match validation; do not accept arbitrary versions.
4. Re-run existing pull-request-job tests to prove no job regression.

## Coordinator Workspace And OpenCode Policy

LCH setup/apply generates only coordinator-owned files under private
directories. It writes atomically and never follows symlinks.

`AGENTS.md` documents WHAT the coordinator does and WHY:

- It is the sole conversational coordinator for Slack.
- It knows only the repository catalogue supplied in the workspace.
- It can answer questions and perform web research.
- It cannot modify repositories or claim repository work was completed.
- When repository changes are needed, it identifies the likely repository and
  objective and states that execution is unavailable in Phase 1.
- It writes concise responses suitable for Slack.
- It does not ask interactive questions through OpenCode's `question` tool; it
  asks in its normal response so the next Slack turn supplies context.

Use a dedicated `opencode.coordinator.json`:

```text
share                deny/disabled
read/list/glob/grep  allow inside workspace
websearch/webfetch   allow
edit/write/patch     deny
bash/shell           deny
external_directory   deny
question             deny
plugins/MCP/LSP      disabled unless later required explicitly
```

OpenCode receives only isolated HOME/XDG paths, its config and basic-auth
credentials, PATH, and locale. It must not receive Slack, GitHub, daemon API,
ngrok, SSH, or Git credentials.

## Inbound Slack Contract

The dedicated FastAPI app exposes only:

```text
POST /slack/events
```

It has no OpenAPI docs, control routes, attach route, cookies, or generic proxy.

Request sequence:

1. Stream the raw body with a configured hard byte limit, including when
   `Content-Length` is absent.
2. Require `X-Slack-Request-Timestamp` and `X-Slack-Signature`.
3. Reject a timestamp outside the configured five-minute default window.
4. Compute HMAC-SHA256 over `v0:{timestamp}:{raw_body}` using the signing secret.
5. Compare signatures in constant time.
6. Parse the authenticated body into typed Slack payloads.
7. Require the configured workspace identity.
8. Return a signed `url_verification` challenge without creating a turn.
9. Normalize `event_callback` message events and durably insert them.
10. Wake the worker and return `200` without waiting for OpenCode or Slack Web
    API delivery.

Slack requires a 2xx response within three seconds and retries failed delivery
up to three times. If durable insertion fails, return a retryable 5xx. Duplicate
`event_id` or message identity returns `200` without another turn.

Do not persist raw request envelopes, signatures, deprecated verification
tokens, or authorization arrays. Persist only the normalized fields required to
recover the conversation.

## Persistence

Use a separate coordinator SQLite database. This preserves the current daemon's
single-process database ownership and prevents the timer daemon and always-on
coordinator from sharing one control database.

```text
coordinator_event
  event_id              primary key
  workspace_id
  channel_id
  message_ts
  thread_ts
  actor_id
  bot_id
  client_msg_id
  text
  event_time
  disposition
  created_at

coordinator_conversation
  id                    primary key
  workspace_id
  channel_id
  root_ts
  opencode_session_id
  created_at
  updated_at
  unique(workspace_id, channel_id, root_ts)

coordinator_turn
  id                    primary key
  event_id              unique foreign key
  conversation_id       foreign key
  state
  managed_prompt
  assistant_message_id
  response_text
  error
  retry_not_before
  created_at
  updated_at

coordinator_delivery
  turn_id               foreign key
  chunk_index
  client_msg_id         unique
  text
  state
  slack_message_ts
  retry_not_before
  primary key(turn_id, chunk_index)
```

Also enforce uniqueness on `(workspace_id, channel_id, message_ts)` so Slack
cannot create two turns through different event wrappers for one message.

Turn state:

```text
received
   |
   v
session_ready
   |
   v
prompt_intended -> prompt_submitted -> response_ready
                                          |
                                          v
                                      delivering
                                          |
                                          v
                                      completed

received -> ignored
any recoverable state -> failed or retry_not_before
```

Persist intent before every external effect. Use transactions that claim one
oldest turn at a time. Phase 1 has one worker globally; this makes per-thread
ordering explicit without adding distributed locks.

The coordinator database gets its own linear migration chain and connection
factory with foreign keys, WAL, busy timeout, and mode-0600 enforcement. Never
delete or recreate an existing database during setup, tests, rollback, or
uninstall.

## OpenCode Conversation Contract

Add a narrow coordinator-owned protocol:

```text
create_or_reuse_session(workspace, identity) -> session_id
observe_prompt(workspace, session_id, exact_prompt) -> prompt state
submit_prompt(workspace, session_id, exact_prompt)
wait_for_completion(workspace, session_id, exact_prompt)
completion(workspace, session_id, exact_prompt)
    -> assistant_message_id + text
```

The concrete adapter reuses the existing OpenCode HTTP client. Extend message
DTOs with stable message IDs and extract only terminal assistant text parts
after the exact managed user prompt.

Managed prompts include immutable Slack identity metadata and the user text:

```text
Slack turn
workspace: T...
channel: C...
thread: <root timestamp>
message: <message timestamp>
actor: U...

<message text>
```

On recovery:

- If the exact prompt is absent, submit it.
- If present and active, wait.
- If present and complete, extract the existing response.
- If present but interrupted, resubmit only according to the existing OpenCode
  prompt-recovery rule; never append a second logical turn silently.
- Persist the assistant message ID and complete text before Slack delivery.

Session titles use a deterministic identity derived from workspace, channel,
and root timestamp. The coordinator database remains authoritative for the
mapping; title lookup permits recovery if session creation succeeded before the
mapping checkpoint.

## Slack Reply Delivery

The Slack adapter posts only coordinator output into the originating root
thread. Repository workers do not exist in Phase 1 and will never receive Slack
credentials in later phases.

### Oversized Responses

Slack recommends no more than 4,000 characters in `text` and truncates beyond
40,000. Preserve the full coordinator response in SQLite, then split it into
ordered messages before delivery:

1. Use a 3,500-character maximum including an optional `[N/M]` prefix.
2. Prefer paragraph, newline, then whitespace boundaries.
3. Hard-split only when no boundary exists.
4. Count Unicode code points, not encoded bytes.
5. Post plain text with link/media unfurling disabled.
6. Persist all chunks before posting the first one.
7. Reconstructing chunk text from stored deliveries must reproduce the full
   response exactly after removing numbering.

Do not add file upload in Phase 1. Ordered chunking preserves all output without
adding `files:write` or Slack's multi-step external upload lifecycle.

Slack generally permits one message per second per channel. Deliver chunks at
the configured minimum interval. On HTTP 429, persist Slack's `Retry-After` and
resume later. Do not sleep inside the webhook handler.

Each delivery uses a deterministic UUID `client_msg_id` derived from turn ID
and chunk index. If a crash occurs after Slack accepts a post but before the
checkpoint commits, recovery scans the thread for that `client_msg_id` before
posting again. Completed chunks are never resent.

## Failure And Recovery Policy

- Invalid public requests: reject without persistence.
- Valid unsupported Slack events: persist an ignored disposition and return
  `200`.
- Coordinator database unavailable: return 5xx so Slack retries.
- OpenCode transient/network failure: retain the turn and retry with bounded
  backoff.
- OpenCode terminal error or turn timeout: persist a safe coordinator failure
  response and deliver it once without provider details or credentials.
- Slack network/5xx failure: retain deliveries for retry.
- Slack 429: honor durable `Retry-After`.
- Process restart: recover all non-terminal turns and deliveries in order.
- OpenCode child exit: fail the service so systemd restarts the coordinator and
  recovery reattaches to persisted sessions.
- Shutdown timeout: cancel in-memory work without changing the last durable
  checkpoint.

## Production Lifecycle

Extend LCH setup/apply/uninstall/status/doctor for two new units while retaining
the existing timer daemon:

### `ocint-coordinator.service`

- `Type=simple`
- loads the existing private `daemon.env`
- runs `ocint daemon coordinator run`
- restarts on failure with bounded delay
- uses `UMask=0077`
- starts after network availability
- never prints credentials

### `ocint-coordinator-ngrok.service`

- starts after and requires the coordinator unit
- runs the installed ngrok binary against port `8733`
- requests `${OCINT_NGROK_URL}` explicitly
- disables HTTP inspection to avoid retaining Slack payloads
- loads only the environment needed for the public URL
- restarts on failure

Doctor verifies configuration, file ownership/modes, Slack `auth.test`, channel
access, signing-secret presence, ngrok config, exact OpenCode version, generated
workspace policy, port separation, and systemd payloads. It does not print or
send the signing secret merely to "test" it; real signed callback coverage is
provided by the live E2E.

Uninstall stops and removes coordinator/ngrok units but preserves configuration,
workspace context, OpenCode data, coordinator database, daemon database, and
credentials.

## Autonomous E2E Strategy

The acceptance test must not require a human Slack message. It uses the existing
Slack app as an artificial test actor while production continues to ignore bot
messages.

### Test Shape

```text
opt-in live pytest
    |
    +-> starts production coordinator factories
    +-> starts real coordinator OpenCode server
    +-> starts real ingress and ngrok static URL
    +-> arms one in-memory E2E actor policy with PROBE_ID
    |
    +-> existing bot chat.postMessage(client_msg_id=PROBE_ID)
            |
            v
         real Slack
            |
            v
         real signed message.groups callback
            |
            v
         coordinator -> real OpenCode -> Slack reply
            |
            v
    assert durable and remote evidence
```

The test injects a narrow actor-policy fake that accepts exactly one root message
from the authenticated bot when its `client_msg_id` equals the pre-armed probe
ID. This policy exists only in the live test composition. Production policy
continues to ignore all bot-authored messages, so there is no test flag,
environment backdoor, magic message prefix, or reply loop in production code.

Put the test outside default pytest discovery at:

```text
bin/ocint/tests/live/ocint/daemon/coordinator/test_slack.py
```

It is invoked explicitly and constructs typed live settings from the already
exported daemon environment. It does not add a production smoke subcommand.

### Live Scenario

1. Fail fast unless ports `8733`, `4098`, and ngrok's static domain are free.
2. Use a dedicated persistent live-E2E coordinator database and workspace. Never
   delete the database.
3. Generate a probe UUID and arm the E2E actor policy.
4. Start the real coordinator OpenCode runtime, worker, ingress, and ngrok.
5. Post a root message to `C0955FD2FK4` with the existing bot token and probe ID.
6. Ask the coordinator to return the probe ID and identify `dotfiles` from its
   repository catalogue.
7. Wait with a bounded timeout for the real Slack event receipt.
8. Assert one conversation and one turn use a non-empty real OpenCode session.
9. Assert the turn records a terminal assistant message ID and response.
10. Poll `conversations.replies` and assert the bot reply is in the original
    thread and contains both the probe ID and `dotfiles`.
11. Assert no daemon task, job, worktree, Git, or GitHub publication API was
    called by the coordinator composition.
12. Stop only processes started by the test. Retain marked Slack messages and
    durable E2E records as auditable evidence.

The coordinator's own Slack reply also produces a real event. The E2E policy
accepts only the armed root ID, and normal bot filtering ignores the reply.

### Deterministic E2E And Integration Coverage

The live LLM scenario proves transport and real OpenCode activation but must not
carry all deterministic behavior assertions. Add local E2E coverage using a fake
Slack transport and fake OpenCode gateway for:

- multi-turn session reuse;
- duplicate event delivery;
- restart after prompt submission;
- restart during uncertain Slack delivery;
- OpenCode failure and timeout;
- a response longer than 8,000 characters producing ordered Slack chunks;
- HTTP 429 during the middle chunk;
- Unicode and hard-split boundaries;
- bot-loop prevention;
- absolute absence of task/job/execution calls.

Integration tests use a real local FastAPI/ASGI boundary for Slack signatures
and real local aiohttp fakes for Slack and OpenCode HTTP contracts.

## Acceptance Criteria

### External And Security

- Slack reaches only `POST /slack/events` through the static ngrok URL.
- Every accepted callback has a fresh, valid Slack signature.
- Valid callbacks are durably recorded before the response.
- Callback acknowledgement does not wait for OpenCode or Slack Web API work.
- Slack, ngrok, GitHub, API, and SSH credentials are absent from the OpenCode
  child environment and context workspace.
- OpenCode and daemon control ports remain loopback-only and are not exposed by
  ngrok.

### Conversation

- An authorized Slack root creates one coordinator conversation and one
  OpenCode session.
- Authorized Slack replies reuse that session and preserve turn order.
- Every user-visible reply comes from the coordinator flow and returns to the
  original Slack thread.
- Bot replies cannot recursively create turns.
- Phase 1 cannot create a repository job, worktree, commit, push, or PR.

### Reliability

- Slack retries do not duplicate events, prompts, or responses.
- Coordinator restart resumes every non-terminal turn and delivery.
- Full OpenCode output is persisted before delivery.
- Responses over Slack's recommended size are delivered completely as ordered,
  rate-limited, independently recoverable chunks.
- All database migrations are additive and no database file is deleted.

### Live E2E

- The existing bot autonomously posts the test root.
- Slack delivers the real signed callback through ngrok.
- Durable state proves that the coordinator OpenCode sandbox ran.
- The coordinator identifies the `dotfiles` catalogue entry.
- Slack receives the answer in the same thread.
- No human posts or clicks anything during the test.

## Test Matrix

| Layer | Behavior |
| --- | --- |
| Unit: coordinator service | authorization, prompt construction, ignored events, session identity, chunking, delivery timing |
| Unit: coordinator repository | atomic dedupe, turn claims, checkpoints, retries, ordered deliveries, restart recovery |
| Unit: workspace | deterministic context, no secrets/paths, private mode, no symlink overwrite |
| Integration: Slack ingress | raw-body HMAC, timestamp window, body limit, URL challenge, workspace checks, 2xx/4xx/5xx |
| Integration: Slack client | JSON root/reply posts, deterministic client IDs, replies lookup, 429 and Retry-After |
| Integration: OpenCode | exact prompt observation, assistant ID/text extraction, active/interrupted/error states |
| Integration: lifecycle | coordinator/ngrok systemd payloads, environment isolation, install/apply/uninstall preservation |
| E2E local | event -> coordinator -> OpenCode fake -> chunked Slack fake, including restart cases |
| E2E live | existing bot -> Slack -> ngrok -> ingress -> real OpenCode -> Slack thread reply |
| Architecture | coordinator cannot import tasks, PR jobs, Git, GitHub, or control API |

All normal tests use fake data and GIVEN/WHEN/THEN. Keep one canonical test
module per production module at each test layer.

## File Impact

### New Coordinator Domain

- `bin/ocint/ocint/daemon/coordinator/__init__.py`
- `bin/ocint/ocint/daemon/coordinator/config.py`
- `bin/ocint/ocint/daemon/coordinator/models.py`
- `bin/ocint/ocint/daemon/coordinator/service.py`
- `bin/ocint/ocint/daemon/coordinator/repository.py`
- `bin/ocint/ocint/daemon/coordinator/workspace.py`
- `bin/ocint/ocint/daemon/coordinator/run.py`
- `bin/ocint/ocint/daemon/coordinator/db/connection.py`
- `bin/ocint/ocint/daemon/coordinator/db/schema.py`
- `bin/ocint/ocint/daemon/coordinator/db/migrations/`

### Existing Production Files

- `daemon/cli.py`: add coordinator composition; remove Slack polling from timer
  composition.
- `daemon/config.py`: aggregate coordinator config and settings credentials.
- `daemon/opencode/service.py`: stable assistant response extraction.
- `daemon/opencode/config.py`, `daemon/opencode/__init__.py`: exact supported
  version and completion facade.
- `daemon/slack/config.py`: event workspace/channel policy.
- `daemon/slack/models.py`: Events API and delivery DTOs.
- `daemon/slack/events.py`: dedicated inbound adapter.
- `daemon/slack/client.py`: root/reply posting, reply lookup, rate-limit details.
- `daemon/slack/service.py`, `daemon/slack/repository.py`: remove polling workflow
  ownership and retain only provider behavior still required by coordinator.
- `daemon/slack/__init__.py`: supported event/delivery facade.
- `daemon/lch/systemd.py`, `setup.py`, `service.py`, `doctor.py`, `cli.py`: two
  long-running units, context provisioning, diagnostics, status, cleanup.
- `bin/ocint/tach.toml`: enforce new module boundaries.
- `bin/ocint/config/opencode.coordinator.json`: coordinator tool policy.
- `bin/ocint/config/daemon.example.toml`: coordinator example.
- `bin/ocint/config/daemon.env.example`: keep all runtime environment examples in
  the private daemon environment file.
- `bin/ocint/config/slack-app-manifest.yaml`: declare `message.groups` while
  retaining Socket Mode off.

### Tests

- Mirror every new coordinator production module under unit/integration tests.
- Add `tests/integration/ocint/daemon/slack/test_events.py`.
- Extend the canonical Slack client and OpenCode service integration tests.
- Replace the old Slack-to-PR E2E expectation with Slack-to-coordinator behavior;
  retain historical migration coverage for old tables.
- Add the explicit live test outside default discovery.
- Extend LCH, config, database, and architecture tests in their existing canonical
  modules.

### Documentation

- `docs/daemon/architecture/architecture.md`: process, state, recovery, and
  sandbox diagrams.
- `docs/daemon/architecture/provider-interactions.md`: coordinator-only Slack
  boundary.
- `docs/daemon/configuration.md`: coordinator TOML, Slack app setup, repository
  catalogue, and environment.
- `docs/daemon/security.md`: signing, credential flow, context limitations, and
  OpenCode isolation.
- `docs/daemon/operations.md`: services, recovery, logs, diagnostics, and live
  E2E invocation.
- `docs/daemon/ngrok.md`: read `OCINT_NGROK_URL` from `daemon.env`, dedicated
  systemd service, and no package `.env`.
- `docs/daemon/workflow.md` and package indexes: coordinator conversation and
  explicit Phase 1 limits.

## Implementation Sequence

1. Record the current clean/dirty worktree and preserve all existing user edits.
2. Add failing architecture tests for coordinator isolation and a failing local
   E2E proving Slack-to-coordinator conversation with no job calls.
3. Tidy the OpenCode adapter: update the exact version pin, add message IDs and
   completion text, and prove existing PR job behavior remains unchanged.
4. Add coordinator config/models and generate the private context workspace and
   restrictive OpenCode policy.
5. Add the separate coordinator database, migration chain, repository
   transactions, and recovery tests.
6. Add signed Slack ingress and deterministic event normalization. Prove body
   limits, freshness, durable-before-ack, and deduplication.
7. Add the single coordinator worker and one-thread/one-session behavior.
8. Add complete response persistence, stable chunking, rate-aware Slack delivery,
   and uncertain-delivery recovery.
9. Remove Slack polling from timer-daemon composition and remove dead polling
   behavior without dropping historical tables or data.
10. Add the standalone coordinator command and its bounded startup/shutdown.
11. Add coordinator and ngrok systemd units plus LCH setup/apply/status/doctor/
    uninstall behavior.
12. Update examples, Slack manifest, and documentation to match the implemented
    architecture.
13. Run focused unit/integration/local-E2E verification.
14. Run the full package check and regression suite.
15. Stop any manually running probe/ngrok processes, then run the autonomous live
    E2E against the static Slack Request URL.
16. Review durable evidence and the real Slack thread before declaring Phase 1
    complete.

## Verification Commands

Focused deterministic verification:

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

Architecture and lifecycle verification:

```bash
uv run --directory /home/vikram_orbio_earth/personal/dotfiles-wt \
  --package ocint --frozen pytest \
  bin/ocint/tests/architecture/test_daemon_architecture.py \
  bin/ocint/tests/unit/ocint/daemon/lch \
  bin/ocint/tests/integration/ocint/daemon/test_db.py
```

Full verification:

```bash
just --justfile bin/ocint/justfile test
just --justfile bin/ocint/justfile check
just --justfile bin/ocint/justfile smoke-daemon
```

Autonomous live E2E, with credentials exported from the private daemon
environment and production coordinator/ngrok units stopped to avoid port/domain
conflicts:

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

1. Apply additive coordinator migrations without starting the service.
2. Generate and inspect the coordinator workspace and OpenCode policy.
3. Verify the existing GitHub timer daemon after Slack polling is removed.
4. Start the coordinator locally and validate OpenCode health.
5. Start the coordinator systemd unit.
6. Start the ngrok unit against the already verified static domain.
7. Run the autonomous live E2E in `C0955FD2FK4`.
8. Confirm service restart recovers a queued synthetic turn before normal use.

Rollback:

1. Stop and disable coordinator and ngrok units.
2. Leave Slack Event Subscriptions configured; Slack retries will fail while the
   endpoint is intentionally offline, or disable the subscription manually for
   a prolonged rollback.
3. Preserve coordinator database, workspace, OpenCode data, daemon database, and
   credentials.
4. Keep the existing GitHub timer daemon operational.

No rollback step deletes a `.sqlite` or `.db` file or removes Slack messages.

## Research Basis

- Slack Events API requires a 2xx within three seconds, retries failed events,
  and recommends asynchronous processing:
  <https://docs.slack.dev/apis/events-api/>
- Slack request authentication uses the raw body, a five-minute timestamp
  window, HMAC-SHA256, and constant-time comparison:
  <https://docs.slack.dev/authentication/verifying-requests-from-slack/>
- `message.groups` is the private-channel event and requires `groups:history`:
  <https://docs.slack.dev/reference/events/message.groups/>
- Slack recommends messages at or below 4,000 characters, truncates beyond
  40,000, and generally permits one post per second per channel:
  <https://docs.slack.dev/reference/methods/chat.postMessage>
- OpenCode exposes authenticated session, message, status, and SSE APIs from a
  loopback `opencode serve` process:
  <https://opencode.ai/docs/server/>
