# Slack Events API Smoke Test Plan

## Goal

Prove that the existing Slack app can deliver a real Events API callback through
ngrok to the daemon.

The completed smoke path is:

```text
ocint smoke command
    |
    | chat.postMessage(client_msg_id=PROBE_ID)
    v
existing ocint Slack bot
    |
    | real message.groups event_callback
    v
Slack -> ngrok -> POST /slack/events
                       |
                       +-> bound raw-body read
                       +-> timestamp and HMAC verification
                       +-> workspace and channel validation
                       +-> durable insert by event_id
                       `-> HTTP 200

ocint smoke command -> wait for PROBE_ID receipt -> report success
```

This phase ends at the durable receipt. It does not translate an event into a
thread observation, task, job, OpenCode session, Git operation, or pull request.

## Scope

### Included

- A public `POST /slack/events` route on the existing FastAPI application.
- Signed Slack `url_verification` handling.
- Signed Slack `event_callback` handling for message events in configured
  private channels.
- Raw-body HMAC verification, replay-window validation, body-size limits, and
  workspace validation.
- Durable event receipts and atomic deduplication by Slack `event_id`.
- A supported smoke command that uses the existing bot token to post one root
  message and waits for its matching callback.
- Unit and integration coverage using fake data and an ASGI test client.
- One live ngrok smoke procedure using the existing Slack app.
- Configuration, security, operations, and architecture documentation.

### Excluded

- Event-to-task or event-to-`ThreadObservation` translation.
- Any call from the event route to `SourceRouter`, `TaskCoordinator`, the job
  runner, or OpenCode.
- Replacing existing Slack polling.
- Socket Mode, slash commands, interactive components, and outgoing webhooks.
- A second Slack app or a user token.
- A permanent ngrok systemd unit or production ingress decision.

## Current State

- `daemon/api.py` owns bearer-protected control routes.
- `daemon/cli.py` creates the FastAPI application and all concrete runtime
  dependencies.
- `daemon/slack/service.py` polls private channels and deliberately classifies
  messages from the existing bot as `AGENT_RESPONSE`.
- `SlackClient.post_message()` already supplies a `client_msg_id`, but always
  includes `thread_ts`; a root-message call must omit that field.
- SQLite contains Slack polling, thread, message, and reply state but no Events
  API inbox.
- The Slack manifest has Socket Mode disabled and no event subscriptions.
- Slack signing secrets are not represented in `DaemonSettings` or
  `daemon.env`.

The smoke event can remain a bot-generated event. This phase records the event
before classification and never sends it to polling or task coordination, so no
test-only authorization rule is needed.

## Design

### Tidy, First

Make one preparatory boundary change: create a Slack-owned inbound adapter in
`daemon/slack/events.py` and expose its construction through
`daemon/slack/__init__.py`.

This keeps Slack payloads, signature policy, persistence input, and smoke
behavior in the owning feature. It avoids putting Slack-specific behavior in
`daemon/api.py`, which remains the bearer-protected control API. No unrelated
polling, task, job, or lifespan refactor is justified for this phase.

### Configuration

Add optional event policy to `SlackConfig`:

```text
[slack.events]
max_request_bytes = 65536
timestamp_tolerance_seconds = 300
smoke_timeout_seconds = 30
receipt_poll_interval_seconds = 1
```

Model it as `SlackEventsConfig | None`. The presence of `[slack.events]` enables
the route and makes the signing secret mandatory. Existing polling-only Slack
configurations remain valid without compatibility branches in runtime code.

Add `OCINT_DAEMON_SLACK_SIGNING_SECRET` as a `SecretStr` setting. Pass its
validated value from `daemon/cli.py`; Slack runtime code must not receive
`DaemonConfig` or read the environment.

The smoke command requires `--channel CHANNEL_ID`, and the channel must already
exist in `SlackConfig.channels`. This avoids a second test-channel registry and
ensures the app is expected to have private-channel access. Because the message
comes from the existing bot, the current polling source continues to classify
it as an agent response.

### Endpoint Contract

`POST /slack/events` is intentionally outside daemon bearer authentication.
Slack authentication is its only authentication mechanism.

Request processing order:

1. Stream the raw request body and stop once `max_request_bytes` is exceeded.
2. Require `X-Slack-Request-Timestamp` and `X-Slack-Signature`.
3. Reject timestamps outside `timestamp_tolerance_seconds` before parsing JSON.
4. Compute HMAC-SHA256 over `v0:{timestamp}:{raw_body}` with the signing secret.
5. Compare the expected and supplied signatures with constant-time comparison.
6. Parse the authenticated payload into Slack-owned immutable models.
7. Require `team_id` to match `SlackConfig.workspace_id`.
8. For `url_verification`, return the challenge without persistence.
9. For a supported message callback in a configured channel, durably insert a
   normalized receipt before returning `200`.
10. Acknowledge authenticated unsupported events and events from other channels
    without persistence.

Responses:

| Condition | Response |
| --- | --- |
| Valid URL verification | `200` with the challenge |
| New, duplicate, or ignored valid callback | `200` |
| Missing, invalid, or stale Slack authentication | `401` |
| Authenticated payload from another workspace | `403` |
| Oversized request | `413` |
| Malformed supported payload | `400` |

Do not log raw bodies, message text, bot tokens, signing secrets, or complete
signatures.

### Durable Receipt

Add an additive Alembic migration and matching SQLAlchemy table named
`slack_event_receipt`:

```text
slack_event_receipt
-------------------
event_id          TEXT PRIMARY KEY
workspace_id      TEXT NOT NULL
event_type        TEXT NOT NULL
channel_id        TEXT NOT NULL
actor_id          TEXT NOT NULL
bot_id            TEXT NOT NULL
message_ts        TEXT NOT NULL
client_msg_id     TEXT NOT NULL
received_at       TEXT NOT NULL
```

Add an index over `(workspace_id, channel_id, client_msg_id)` for smoke lookup.
Do not persist the complete Slack envelope or message body. The receipt proves
delivery while minimizing retained Slack content.

Use one atomic SQLite insert with conflict-ignore semantics on `event_id`, then
read the durable row. Slack retries return `200` and preserve the first receipt.

Repository operations remain domain-oriented:

```text
record_event(receipt) -> durable original receipt
event_for_probe(workspace_id, channel_id, client_msg_id) -> receipt | none
```

### Existing-App Smoke Command

Add:

```bash
ocint daemon slack-events-smoke --channel C01234567
```

The command:

1. Requires `[slack.events]`, the bot token, and a configured channel.
2. Migrates the daemon database before opening the receipt repository.
3. Calls Slack `auth.test` and requires the configured workspace.
4. Generates one UUID and uses it as `client_msg_id` and in harmless marker
   text such as `ocint Slack Events API smoke <uuid>`.
5. Posts a root message through the existing app.
6. Polls the receipt repository until the matching callback arrives or the
   configured timeout expires.
7. Prints JSON containing the probe ID, Slack `event_id`, channel, and message
   timestamp, then exits zero.
8. Exits nonzero on timeout or any configuration/authentication mismatch.

Change `SlackClient.post_message()` so an empty thread timestamp omits
`thread_ts` from `chat.postMessage`; preserve the current threaded-reply shape
when a timestamp is present.

The smoke command is preferable to a live pytest. It is a repeatable operator
diagnostic, while normal tests remain deterministic and contain no real Slack
credentials or ngrok dependency.

## Module Boundaries

```text
daemon/config.py
    `-> parses secret setting only

daemon/cli.py
    +-> constructs Slack event router
    +-> injects Slack policy, secret, clock, and repository
    `-> invokes Slack smoke facade from the CLI command

daemon/slack/
    +-> config.py       event policy
    +-> models.py       callback and receipt models
    +-> events.py       HTTP adapter, signature verification, smoke workflow
    +-> repository.py   durable receipt operations
    +-> client.py       root-message transport support
    `-> __init__.py     supported construction and smoke operations

daemon/api.py           unchanged control API
daemon/tasks/           unchanged and unreachable from event receipt
daemon/pull_request_job unchanged and unreachable from event receipt
```

Inject a clock into signature validation and smoke waiting so tests do not patch
global time. Keep concrete FastAPI and Slack transport construction at feature
or CLI boundaries and pass narrow protocols inward.

## File Changes

### Production

- Add `bin/ocint/ocint/daemon/slack/events.py` for request authentication,
  callback handling, router construction, and the smoke workflow.
- Update `bin/ocint/ocint/daemon/slack/config.py` with optional typed Events API
  policy and positive bounds.
- Update `bin/ocint/ocint/daemon/slack/models.py` with typed URL verification,
  callback, nested message-event, stored receipt, and smoke-result models.
- Update `bin/ocint/ocint/daemon/slack/repository.py` with atomic receipt insert
  and probe lookup.
- Update `bin/ocint/ocint/daemon/slack/client.py` to support root posts without
  sending an empty `thread_ts`.
- Update `bin/ocint/ocint/daemon/slack/__init__.py` to expose only supported
  router construction and smoke operations.
- Update `bin/ocint/ocint/daemon/config.py` with the signing-secret setting.
- Update `bin/ocint/ocint/daemon/cli.py` to compose the optional router and add
  `slack-events-smoke`.
- Update `bin/ocint/ocint/daemon/db/schema.py` with the receipt table and index.
- Add the next linear migration under
  `bin/ocint/ocint/daemon/db/migrations/versions/` after
  `20260724_add_slack`.
- Update LCH environment handling and diagnostics so a configured Events API
  requires and preserves `OCINT_DAEMON_SLACK_SIGNING_SECRET` without printing
  it.

### Tests

- Add `bin/ocint/tests/integration/ocint/daemon/slack/test_events.py` as the one
  canonical endpoint module.
- Extend `tests/unit/ocint/daemon/slack/test_repository.py` for first-write-wins
  deduplication and probe lookup.
- Extend `tests/integration/ocint/daemon/slack/test_client.py` for root versus
  threaded message request shapes.
- Extend the existing daemon config, CLI, database migration, LCH, and
  architecture test modules rather than creating suffix variants.

Tests must use fake Slack transport data and real temporary SQLite databases.
They must not patch Slack, ngrok, or environment-global behavior.

### Configuration And Documentation

- Update `bin/ocint/config/slack-app-manifest.yaml` with an Events API bot
  subscription for private-channel messages while retaining Socket Mode off.
- Update `bin/ocint/config/daemon.example.toml` with optional `[slack.events]`.
- Update `bin/ocint/config/daemon.env.example` with the signing secret.
- Update daemon configuration, security, operations, architecture, workflow,
  and package index documentation to describe receipt-only behavior and the
  live smoke command.
- Preserve all existing ASCII diagrams; revise any statement that Slack event
  delivery is disabled.

## Test Scenarios

### Endpoint

1. A fresh, correctly signed URL verification returns its challenge and stores
   no receipt.
2. A fresh, correctly signed bot message callback for a configured channel is
   stored before a `200` response.
3. Delivering the same `event_id` twice returns `200` twice and leaves one
   immutable receipt.
4. Missing, malformed, incorrect, and stale signatures return `401` and store
   nothing.
5. A body over the configured limit returns `413`, including when no
   `Content-Length` is supplied.
6. A validly signed callback claiming another workspace returns `403`.
7. Unsupported event types and unconfigured channels return `200`, store
   nothing, and invoke no downstream dependency.
8. Receipt handling leaves `task`, `task_job`, and `job` empty.

### Persistence And Client

1. Concurrent or repeated insertion of one `event_id` preserves one row.
2. Probe lookup requires workspace, configured channel, and exact
   `client_msg_id`.
3. Root posting omits `thread_ts`; reply posting retains it.
4. The migration upgrades from the current head without losing existing Slack
   polling data and downgrades only the new receipt table.

### Composition And CLI

1. Polling-only Slack configuration does not expose the event route or require a
   signing secret.
2. `[slack.events]` without a signing secret fails before serving.
3. The router is present when event policy and secret are supplied.
4. The smoke command rejects an unconfigured channel and workspace mismatch.
5. A fake callback receipt makes the smoke command print its identifiers and
   exit zero; timeout exits nonzero.

## Acceptance Criteria

- Slack verifies the ngrok request URL successfully.
- `ocint daemon slack-events-smoke --channel CHANNEL_ID` posts through the
  existing app and succeeds without a human Slack message.
- The reported `event_id`, channel, timestamp, and `client_msg_id` correspond to
  one durable receipt.
- Repeated Slack delivery cannot create a second receipt.
- No task, job, OpenCode session, Git operation, or pull request is created from
  the callback.
- Existing polling and Slack reply behavior remain unchanged.
- The signing secret and message body never appear in logs or receipt storage.
- All focused tests and repository checks pass.

## Implementation Sequence

1. Add failing endpoint, repository, client-shape, config, and composition tests
   that prove the acceptance behavior and the absence of task/job rows.
2. Tidy first by introducing the Slack-owned event adapter and facade contract;
   do not move or refactor existing polling logic.
3. Add typed event policy, payload models, receipt models, and the signing-secret
   settings boundary.
4. Add the schema and linear Alembic migration, then implement atomic receipt
   persistence and lookup.
5. Implement bounded raw-body reading, timestamp validation, constant-time HMAC
   verification, typed payload parsing, workspace/channel filtering, URL
   verification, persistence, and acknowledgements.
6. Compose the router only when `[slack.events]` is present.
7. Add root-message support and the smoke workflow/CLI command.
8. Update LCH secret preservation and diagnostics.
9. Update the Slack manifest, examples, and daemon documentation.
10. Run focused tests, full package checks, then the live ngrok smoke.

## Verification

Focused verification:

```bash
uv run --directory /home/vikram_orbio_earth/personal/dotfiles-wt \
  --package ocint --frozen pytest \
  bin/ocint/tests/integration/ocint/daemon/slack/test_events.py \
  bin/ocint/tests/unit/ocint/daemon/slack/test_repository.py \
  bin/ocint/tests/integration/ocint/daemon/slack/test_client.py \
  bin/ocint/tests/integration/ocint/daemon/test_api.py \
  bin/ocint/tests/integration/ocint/daemon/test_cli.py
```

Full verification:

```bash
just --justfile bin/ocint/justfile test
just --justfile bin/ocint/justfile check
just --justfile bin/ocint/justfile smoke-daemon
```

Live verification after automated checks:

```bash
ocint daemon migrate
ocint daemon run
ngrok http 8732 --domain YOUR_STATIC_DOMAIN.ngrok-free.dev
ocint daemon slack-events-smoke --channel CHANNEL_ID
```

Confirm the smoke output identifies one receipt and inspect daemon status only
through supported commands. Do not inspect or modify database files directly,
and never delete a `.sqlite` or `.db` file.

## Deferred Next Seam

A later plan may consume durable Slack event receipts and translate them into
provider-neutral thread observations. That work must define acknowledgement
versus processing failure semantics, polling coexistence or removal, durable
consumer checkpoints, authorization, follow-ups, and daemon wake/lifetime
behavior. None of those decisions are needed to prove this endpoint.
