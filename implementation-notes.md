# Implementation Notes

## Slack Coordinator Phase 1

### Correlate OpenCode by caller message ID

**Decision:** Submit a deterministic `msg_`-prefixed user message ID and recover
the assistant by its `parentID` instead of matching prompt text.

**Rationale:** A live OpenCode 1.18.15 probe confirmed caller IDs, stable
assistant IDs, parent IDs, terminal finish state, and ordered text parts.

**Consequence:** Retries and restarts can identify the exact logical turn
without depending on mutable prompt content.

### Preserve completed responses on delivery failure

**Decision:** Retry classified Slack and OpenCode transport failures durably. An
unclassified terminal Slack delivery failure stops the coordinator service
instead of replacing an already persisted assistant response.

**Rationale:** Delivery is a later external effect. Changing the response after
delivery starts would corrupt durable conversation history.

**Consequence:** systemd recovery resumes the same response and chunk identity.

### Bound ingress database contention

**Decision:** Use a 2,000 ms SQLite busy timeout and a 2.5 second ingress
processing budget by default, with configuration validation keeping both below
Slack's three-second acknowledgement deadline.

**Rationale:** Tidy, First moved contention policy to shared database setup while
keeping the transport deadline at the Slack boundary.

**Consequence:** Contended callbacks return `503` for Slack retry without
acknowledging before commit or blocking the event loop.

### Provision current installations idempotently

**Decision:** `lch setup` and `lch apply` provision and validate coordinator
policy and authentication artifacts for an existing current-format daemon
configuration before installing units.

**Rationale:** This host already runs the timer daemon; coordinator rollout must
not require deleting or recreating its database or credentials.

**Consequence:** Compatibility with the superseded polling TOML is not provided,
but repeated apply operations preserve state and root configuration.

### Clear the ngrok process environment

**Decision:** Resolve and validate an absolute ngrok v3 executable, then launch
it through `env -i` with only HOME, XDG config, and locale values. Pass the
validated static URL as a command argument.

**Rationale:** Loading the shared daemon environment directly would expose Slack,
GitHub, API, and signing credentials to ngrok.

**Consequence:** ngrok can read its own configuration but cannot inherit daemon
secrets.

### Omit thread identity for Slack root posts

**Decision:** Do not send `thread_ts` when posting a root message.

**Rationale:** An empty thread timestamp is not the same contract as an absent
thread timestamp.

**Consequence:** The autonomous probe creates an unambiguous Slack root whose
returned timestamp becomes the durable conversation identity.

### Use authorized user OAuth for the E2E actor

**Decision:** The authorized test user posts the autonomous probe with an xoxp
User OAuth Token issued through the separately created `ocint E2E actor` app.
The app grants user OAuth `chat:write` and was reinstalled after that scope was
added. The token stays in mode-0600 `live-e2e.env`, outside `daemon.env` and
systemd. Test composition arms an exact one-probe classifier for the configured
workspace, public channel, authorized user, UUID `client_msg_id`, and prompt.

**Rationale:** The corrected `message.channels` subscription produced valid,
signed callbacks with HTTP `200` for both a Slack UI post and an xoxp post in
public channel `C0955FD2FK4`. The UI callback carried authorized user
`U067EG8278R` with no bot/app IDs. The xoxp callback carried the same user plus
`bot_id=B0BNRPSUB8W`, `app_id=A0BNQBTV022`, and the caller's exact
`client_msg_id`; Slack therefore classifies the API-authored post differently
from a UI-authored human post.

**Consequence:** Exact retries of the armed event reach repository deduplication,
while every other bot/app event remains rejected. Production classification is
unchanged and has no environment switch or backdoor. The production bot remains
the delivery client, and the explicit harness sources both private environment
files while preserving Slack messages and shared-database rows.

### Parse private payloads but execute public payloads only

**Decision:** Model `channel_type="channel"` and `channel_type="group"` message
payloads as a normal Pydantic typed union. Translate only the public variant;
private payloads parse but are durably ignored before authorization. Deploy only
`message.channels` with `channels:history`; private translation, subscription,
and scope remain a documented FIXME.

**Rationale:** Channel visibility controls Slack's event and OAuth contract. The
proven target is public, so requesting `message.groups`/`groups:history` was both
incorrect and broader than the deployed requirement.

**Consequence:** Sanitized UI and xoxp callback fixtures protect the observed
public contract. Supporting private channels later requires an explicit
manifest, access-validation, documentation, and live-contract change.

### Put lifecycle and ingress ownership in their feature facades

**Decision:** The coordinator facade owns its runtime lock, OpenCode child,
worker/ingress supervision, and bounded shutdown through generic injected
contracts. Slack owns one cohesive ingress object; its FastAPI route delegates
to that object.

**Rationale:** Tidy, First keeps the CLI as composition root without making it a
workflow owner, preserves the coordinator-to-Slack dependency prohibition, and
lets the live harness exercise the same production lifecycle. The ingress owner
can also return `503` at its deadline while observing, rather than awaiting, a
shielded late database thread.

**Consequence:** A timed-out request never wakes the worker; a late commit is
recovered by durable scanning and Slack retry deduplication. Safe structured
checkpoints correlate ingress, turns, OpenCode, delivery, child exit, and
shutdown without logging content or credentials.

### Preserve classified OpenCode recovery without duplicate submission

**Decision:** Provider-observed terminal and retryable assistant errors remain
typed exceptions through the OpenCode and coordinator adapters. Terminal errors
persist and deliver the safe response. Retryable errors and inactive incomplete
prompts schedule durable retry without resubmitting; only an absent managed
prompt is submitted.

**Rationale:** A deterministic message ID identifies the logical prompt but does
not prove that repeating a provider request after a persisted error is harmless.

**Consequence:** Restart recovery cannot duplicate a managed user message and a
terminal persisted error cannot be mistaken for interruption.

### Bound OpenCode retries without bounding Slack delivery

**Decision:** As a material Tidy, First reliability rule, configure
`max_turn_retries` as a positive coordinator field with default `3`. The value
counts durable retry schedules after the initial OpenCode attempt, so `3`
permits at most four processing attempts. On the next retryable OpenCode error
or interrupted prompt observation, persist and deliver the existing safe
failure response. Do not apply this budget to
`RetryableCoordinatorDeliveryError`; Slack retries remain unbounded and resume
the response already persisted.

**Rationale:** An indefinitely retryable or inactive incomplete managed prompt
held the conversation's ordering gate forever. A typed composition-time policy
is explicit and testable without hiding reliability behavior in a module
constant. Delivery is a separate external effect and must not replace or
abandon a valid persisted response.

**Consequence:** A failed turn reaches its terminal `failed` state after safe
response delivery and the next ordered turn can run, without duplicate prompt
submission. Slack can continue retrying past the OpenCode budget while retaining
the original response and failure classification.

### Keep provider output out of the service journal

**Decision:** Start OpenCode without `--print-logs` and connect child stdin,
stdout, and stderr to `/dev/null`.

**Rationale:** Coordinator journald output is not an approved sink for prompts,
responses, or provider diagnostics.

**Consequence:** Health, version, exit status, and redacted adapter events remain
observable without inheriting provider output.

### Reject database-file symlinks before database lifecycle work

**Decision:** Engine creation, upgrade, and downgrade reject a configured
database file that is itself a symlink before resolution or open. Parent
directory aliases remain supported and converge on the canonical migration lock.

**Rationale:** Following a database-file symlink could migrate or chmod an
unrelated target.

**Consequence:** Rejected targets retain their bytes and mode, while existing
parent-directory alias behavior is unchanged.

### Preserve asynchronous ingress and credential boundaries

**Decision:** Cancellation attaches the same late-ingest observer used by the
deadline path and re-raises immediately. The central subprocess scrub policy
always removes the live xoxp actor token, including from explicit helper
environments and direct live-harness subprocesses.

**Rationale:** Request cancellation must not wait indefinitely for SQLite, and a
test-only Slack credential must reach only the actor client.

**Consequence:** Late commits are recovered by durable scanning without worker
wakeup, and systemctl/ngrok/OpenCode cannot inherit the actor token.

### Preserve and report coordinator unit enablement

**Decision:** Initial setup never enables coordinator units. Later setup/apply
regenerates units without enabling or disabling them, reads their actual
unit-file states, and reports those states.

**Rationale:** Silently disabling production on apply is unsafe, while claiming
`enabled=no` for pre-enabled units is misleading.

**Consequence:** Operators explicitly disable units for test windows and apply
preserves an already enabled deployment.

### Give the coordinator one graceful restart owner

**Decision:** As an out-of-plan Tidy, First correction, the coordinator facade
registers temporary SIGTERM/SIGINT handlers before OpenCode startup and owns
requested shutdown, bounded worker/ingress close, and subsequent OpenCode close.
Its explicitly signal-free Uvicorn ingress serves only from the injected
shutdown event; the generic daemon retains normal Uvicorn signal ownership. The
systemd unit uses `KillMode=mixed`.

**Rationale:** Signaling the parent, OpenCode child, and Uvicorn independently
made an ordinary systemd restart look like an unexpected child failure and
could bypass bounded cleanup.

**Consequence:** A signal during startup cancels startup, closes OpenCode,
restores prior handlers, and exits normally. Once running, unexpected supervised
completion takes precedence over a concurrent shutdown request. Graceful restart
still completes bounded shutdown before OpenCode close and leaves timeout cgroup
cleanup to systemd.

### Reject unsafe database and configuration files before mutation

**Decision:** Database lifecycle rejects a database-file symlink before opening
it. LCH setup/apply likewise validate daemon TOML and source OpenCode JSON as
user-owned regular non-symlink mode-0600 files before parsing, provisioning, or
unit writes. Parent-directory symlink aliases are canonicalized; the final file
component is never resolved through a symlink.

**Rationale:** A convenient parent alias can safely converge on one canonical
lock and path, while following a configured file symlink could parse, migrate,
chmod, or replace an unrelated target.

**Consequence:** Unsafe inputs fail without changing managed files, units, or
database bytes. Doctor uses the same typed private-file contract.

### Preserve terminal events after orphan expiry

**Decision:** Once an awaiting-root conversation expires, later provider events
for that terminal conversation remain durably classified and cannot reactivate
it or create turns.

**Rationale:** Expiry is a terminal workflow decision, not a temporary absence
of an eligible root.

**Consequence:** Delayed and retried Slack events remain observable without
reopening completed retention policy.

### Complete thread identity in a follow-up migration

**Decision:** Keep the additive coordinator migration and add a second migration
that completes immutable message/thread identity needed by follow-up turns.

**Rationale:** The approved core schema had already shipped in the stack; an
additive follow-up preserves the migration chain and existing rows.

**Consequence:** Root and follow-up events correlate deterministically without
rewriting the first migration.

### Keep the coordinator facade lazy and protocol-shaped

**Decision:** Export narrow coordinator protocols and construction operations
from a lazy facade. Concrete repository, OpenCode, workspace, and runtime modules
load only when their factory or workflow is called.

**Rationale:** The provider-neutral core must not depend on Slack or eagerly
initialize runtime adapters.

**Consequence:** CLI remains the composition root, Slack depends on coordinator
contracts, and Tach enforces the split.

### Generate workspace context only at coordinator startup

**Decision:** Coordinator startup is the single owner of atomic `AGENTS.md` and
`repositories.json` generation because it has the final validated repository
projection. LCH owns private directories plus policy/auth provisioning only.

**Rationale:** A second LCH generator could drift from the projection actually
used when OpenCode starts.

**Consequence:** Doctor reports context as pending before first coordinator
startup rather than treating absence as an LCH provisioning failure.

### Validate stacked changes without release behavior

**Decision:** Validate this work as the cumulative core -> Slack -> operations
stack, with each upper branch remaining a descendant of its updated approved
parent. Do not invoke release preparation or publication for stack review.

**Rationale:** Review fixes must preserve approved lower-stack contracts while
avoiding unrelated release mutations.

**Consequence:** Tests, static checks, smoke checks, package build, and explicit
live-marker collection are the acceptance surface; external live E2E remains a
separate final operator action.
