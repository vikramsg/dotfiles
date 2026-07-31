# Slack Channels Plan

## Objective

Add Slack as a second durable daemon channel while preserving the existing
GitHub issue workflow. A user can post work in a configured Slack channel, the
daemon creates the same task and execution flow used for GitHub issues, GitHub
publishes the resulting pull request, and the daemon replies in the originating
Slack thread.

The work begins with a tidy-first separation of existing responsibilities:

```text
channel domain   -> conversations, messages, replies, completion
task domain      -> batching, follow-ups, retries, task state
execution domain -> OpenCode, Git, validation, commit, push, publication
lifecycle domain -> setup, systemd, diagnostics, bounded invocation
```

GitHub issue communication and GitHub pull-request publication become separate
capabilities. Slack implements the channel capability only. No generic plugin
framework, generic lifecycle framework, or shared Slack/GitHub HTTP abstraction
is introduced.

All implementation changes must be split into small reviewable pull requests.
PR titles use the required `ocint: summary` format. Nothing is committed or
pushed directly to `main`.

## Decisions And Assumptions

1. Slack is polled through the Web API. There is no Socket Mode, Events API,
   webhook, slash command, or continuously connected Slack process.
2. One configured Slack workspace may contain multiple configured channels.
3. Each Slack channel maps to exactly one configured repository.
4. Every ordinary root message in a configured Slack channel requests work.
5. The first non-empty line of a Slack root message becomes the work title. The
   complete unchanged message remains part of the prompt.
6. Slack user IDs, workspace IDs, channel IDs, timestamps, and bot user IDs are
   used as immutable identities. Display names are never authorization keys.
7. Slack actor authorization is configured per channel. An empty allowlist has
   the same meaning as the current GitHub policy: any authenticated channel
   member is permitted.
8. A Slack root message is the thread identity. Slack replies are follow-up
   messages within that thread.
9. Successful completion posts the shared provider-neutral completion text in
   the originating thread, adds the configured reaction to the root, and marks
   the thread closed in daemon persistence.
10. The default completion reaction is `white_check_mark`.
11. Closed Slack threads are not polled through `conversations.replies`.
12. Reopening is explicit and discoverable without polling closed threads. An
    authorized user posts a new root message in the same configured channel:

    ```text
    reopen <Slack root-message permalink>
    ```

13. A reopen message is control input, not prompt input. It reopens a known
    closed root from the same workspace and channel, then the daemon fetches
    that root's replies. Replies added while closed are ingested once.
14. Unknown, malformed, cross-workspace, cross-channel, non-root, open-thread,
    or unauthorized reopen requests do not change task state and receive one
    idempotent explanatory reply.
15. A shared completion message replaces the current GitHub-specific wording:

    ```text
    Work addressed: <pull-request-url>
    ```

    Both GitHub and Slack receive this exact domain-owned result. GitHub may
    continue accepting ordinary issue comments without an explicit reopen
    because an open GitHub issue already provides a native lifecycle boundary.
    Slack communicates its closed state with the root reaction and documented
    reopen command rather than provider-specific completion prose.
16. Pull-request publication remains an execution stage. Slack never publishes
    pull requests.
17. A durable work stream owns at most one pull request. A follow-up reuses its
    open pull request; a closed or merged owned pull request is not replaced.
18. Existing jobs, GitHub threads, messages, tasks, attempts, and pull-request
    ownership survive migration. No reset migration or database deletion is
    permitted.
19. Slack is optional. A configuration without Slack continues operating as the
    GitHub-only daemon.
20. Live Slack tests are opt-in and use a disposable workspace/channel. They do
    not run in default CI.

## Target Dependencies

```text
daemon CLI composition
  |
  +--> channel contracts <--------- GitHub issue channel
  |                            `---- Slack conversation channel
  |
  +--> task coordinator ----------> channel contracts
  |                            `---- execution contract
  |
  +--> execution contracts <------- GitHub PR publisher
  |                            +---- OpenCode adapter
  |                            `---- Git adapter
  |
  +--> LCH lifecycle
  `--> physical DB lifecycle
```

Forbidden dependencies:

```text
tasks       -X-> GitHub or Slack modules
channels    -X-> execution implementation
publication -X-> GitHub issue or Slack thread models
Slack       -X-> GitHub transport
GitHub PR   -X-> channel reply behavior
```

Consumer-owned protocols stay with the consuming domain. Concrete adapters are
constructed only in `ocint/daemon/cli.py` and passed inward.

## Module Ownership

The target movement is domain-first. It is not a generic clean-architecture
layer split.

### Channels

Create `bin/ocint/ocint/daemon/channels/` to own:

- Provider-neutral channel, thread, message, actor, observation, reply, and
  completion models.
- The channel protocol consumed by task coordination.
- Durable channel/thread/message persistence semantics.
- Fixed channel dispatch used by `TaskCoordinator`.

Move GitHub issue behavior from the combined `GitHubService` into
`channels/github/`:

- `config.py`: issue label and GitHub issue-channel policy.
- `models.py`: issue/comment API DTOs and GitHub issue identities.
- `client.py`: issue and comment endpoint operations.
- `service.py`: `GitHubChannel`, classification, observation, replies.
- `repository.py`: issue/comment mappings and reply markers.
- `__init__.py`: supported channel facade only.

Add `channels/slack/`:

- `config.py`: workspace, channel mappings, authorized users, completion
  reaction.
- `models.py`: Slack API DTOs and validated Slack IDs/timestamps/permalinks.
- `client.py`: Slack Web API methods and Slack-specific error handling.
- `service.py`: `SlackChannel`, polling translation, replies, completion,
  closure, and reopening.
- `repository.py`: Slack mappings, watermarks, cursors, deliveries, reactions,
  closure, and retry state.
- `__init__.py`: supported Slack facade and lifecycle factory.

### Tasks

Keep `bin/ocint/ocint/daemon/tasks/` focused on:

- Task batching and task/message coverage.
- Initial, follow-up, retry, addressed, skipped, and errored transitions.
- Building provider-neutral `WorkRequest` values.
- Routing replies/completion through the channel identified by a task thread.

`TaskCoordinator` no longer receives one `ThreadSource`. It receives a fixed
tuple of `Channel` implementations. This is static dependency injection, not a
runtime plugin registry.

### Execution

Create `bin/ocint/ocint/daemon/execution/` and move current execution-owned
behavior without changing it:

- Root `service.py` to execution orchestration.
- Root `repository.py` to execution job persistence.
- Root `git.py` and `opencode.py` to execution adapters.
- Job, stage, checkpoint, publication, and attachment models out of root
  `daemon/models.py` into their owner.

Put GitHub PR endpoint behavior under `execution/publication/github/`:

- `models.py`: pull-request API DTOs.
- `client.py`: pull lookup/create endpoint operations.
- `publisher.py`: execution-owned publication protocol implementation.
- `repository.py`: provider-neutral owner-to-PR mapping behavior.

### Shared GitHub Transport

Keep a narrow `bin/ocint/ocint/daemon/github/` provider mechanism because both
channel and publication capabilities use one authenticated GitHub lifecycle:

- `config.py`: GitHub API base URL only.
- `transport.py`: authenticated aiohttp session, raw requests, response/error
  handling, and pagination mechanism.
- `__init__.py`: lifecycle facade used by CLI composition.

The shared transport does not expose `issues()`, `comments()`, `pulls()`, or
provider DTOs. Capability-specific clients own those endpoints and validation.
Slack keeps its transport local because it currently supports only one domain
capability. Do not extract a generic provider HTTP package.

### Lifecycle And Physical Database

Keep `lch/` and `db/` in their current ownership roles:

- `lch/` owns setup, private credentials, systemd, diagnostics, and operator
  commands.
- `db/` owns physical SQLAlchemy metadata, connection policy, and Alembic.
- Domain repositories own queries, transactions, and state-transition rules.

Update `tach.toml` to enforce these dependencies. Do not add AST tests that
duplicate Tach.

## Core Contracts

Replace `GitHubLogin` and composite provider strings in shared contracts with
frozen typed identities constructed at provider boundaries:

```text
ProviderId
ProviderScopeId
ProviderConversationId
ProviderThreadId
ProviderMessageId
ProviderActorId

ActorIdentity
  provider
  scope
  actor

ChannelThreadIdentity
  provider
  scope
  conversation
  thread

ChannelMessageIdentity
  thread identity
  message
```

The channel protocol supports the behaviors task coordination requires:

```text
observe -> complete channel observations
reply   -> unauthorized/refusal/informational response
complete -> completion response plus provider-owned completion effects
```

`complete` allows Slack to post the result, add its reaction, and close its
thread with restart-safe checkpoints. The GitHub implementation posts the
comment and retains GitHub's issue lifecycle behavior.

`WorkRequest` contains:

- Provider-neutral actor identity.
- Configured repository name.
- Canonical title and prompt.
- Durable channel thread and anchor identity, or direct origin.
- Provider-neutral publication owner key.

`PublicationRequest` contains only execution concerns:

- Repository.
- Branch and base.
- Title and body.
- Provider-neutral publication owner key.

It must not contain `ThreadOrigin`, GitHub issue IDs, Slack IDs, or a channel
implementation type.

## Pull-Request Ownership

Replace the current issue-coupled ownership in `github_issue` with a durable
provider-neutral publication owner:

```text
publication_owner
  repository
  owner_key
  pull_request_number
  pull_request_url
```

The unique business key is `(repository, owner_key)`. A channel-origin task
derives `owner_key` from its immutable channel thread identity. Direct API jobs
derive `direct:job:<job-id>`.

The GitHub publisher performs:

1. Load existing ownership by repository and owner key.
2. If owned, fetch that PR and return it when open.
3. Refuse publication when the owned PR is closed or merged.
4. Otherwise find an existing open PR by branch/base.
5. Create one only when none exists.
6. Persist ownership before returning success.

This preserves follow-up reuse and closed-PR refusal for both GitHub- and
Slack-originated work without publication inspecting channel origins.

## Persistence And Migration

Use additive, non-destructive Alembic revisions. Never delete a database file
or reset existing task data.

### Core Channel Revision

Add a durable configured channel table with a unique provider identity and a
repository mapping. Add typed channel identity columns to `thread` and typed
message/actor identity columns to `thread_message`.

Migration sequence:

1. Create new channel and identity columns/tables as nullable migration state.
2. Insert one GitHub channel row per existing configured GitHub repository.
3. Resolve every existing `thread.source_id` through `github_issue` and backfill
   provider, scope, conversation, and thread identities.
4. Resolve every existing `thread_message.source_id` through the issue/comment
   mappings and backfill provider message and actor identities.
5. Backfill job channel origins from existing origin columns.
6. Verify copied row counts, missing mappings, unique identities, and foreign
   keys in the migration before making target columns non-null.
7. Rebuild affected SQLite tables only after successful backfill.
8. Preserve primary keys so `task`, `task_message`, and `task_job` links remain
   valid.
9. Remove obsolete source columns only after all code reads typed identities.

Required uniqueness:

- Configured channel provider identity.
- Thread identity within a channel.
- Message identity within a thread.
- Existing task/message and task/job uniqueness.

### Publication Ownership Revision

1. Create `publication_owner`.
2. Backfill each existing non-empty `github_issue.pull_request_*` mapping using
   that issue's new channel thread owner key.
3. Preserve direct jobs and jobs without a published PR.
4. Verify one owner row per existing owned PR before removing PR ownership from
   `github_issue`.
5. Add uniqueness for `(repository, owner_key)` and the provider PR identity.

### Slack Revision

Add Slack-owned state rather than adding Slack columns to core task tables:

- Workspace identity and bot user identity.
- Configured Slack channel mapping.
- Channel history stable watermark.
- In-progress history cursor and cycle upper bound.
- Per-open-thread reply watermark and in-progress cursor.
- Durable `retry_not_before` from Slack `Retry-After`.
- Slack root/message timestamp mappings.
- Reply delivery idempotency key and resulting message timestamp.
- Completion reaction checkpoint.
- Open/closed state and completion timestamp.
- Reopen control message to target-thread linkage.

The stable watermark advances only after every page in a cycle is committed.
Each page and next cursor commit in one transaction. A restart resumes the
incomplete page sequence without skipping or duplicating messages.

## Slack Polling Flow

One bounded reconciliation cycle performs:

1. Skip the workspace/channel while its persisted `retry_not_before` is in the
   future.
2. Call `conversations.history` using the persisted stable watermark, cycle
   upper bound, and cursor.
3. Commit each page, provider mappings, and next cursor atomically.
4. Classify ordinary new roots as actionable or unauthorized.
5. Parse exact root-level `reopen <permalink>` control messages separately.
6. After history pagination completes, advance the stable watermark.
7. Call `conversations.replies` only for tracked open roots.
8. Commit reply pages and cursors atomically.
9. Translate provider messages to complete channel observations.
10. Let normal task reconciliation create or update work.

Slack API calls:

- `auth.test`: startup identity and workspace verification.
- `conversations.history`: new roots and channel access.
- `conversations.replies`: open-thread messages.
- `chat.postMessage`: thread replies and control-message responses.
- `reactions.add`: completion marker.

Every Slack JSON response must validate `ok`. HTTP 429 reads `Retry-After`,
persists a concrete retry time, and ends Slack reconciliation without sleeping
for an unbounded period. Network and 5xx failures leave cursors unchanged and
surface a retryable daemon-cycle failure.

Bot messages are identified by the immutable bot user ID returned by
`auth.test`, classified as `AGENT_RESPONSE`, persisted, and excluded from task
prompts. Unsupported message subtypes, edits, deletions, file-only messages,
and malformed messages need explicit tested policy; the initial implementation
should ignore them without creating work and log only non-sensitive identity
metadata.

## Slack Completion And Reopening

Completion is a durable sequence:

1. Generate the shared completion text from task state and publication result.
2. Find or post the Slack thread reply using a persisted key composed from
   thread identity, outcome, and anchor message identity.
3. Add the configured reaction to the root. Treat Slack `already_reacted` as
   success.
4. Persist the completion-reply and reaction checkpoints.
5. Mark the Slack root closed only after both external effects are confirmed.
6. Mark the task addressed.

On restart, repeat only the first incomplete step. A unique delivery key and a
unique `(root, reaction)` checkpoint prevent duplicate bot output.

Reopening flow:

1. Poll a new root control message through ordinary channel history.
2. Parse the Slack permalink without another API scope.
3. Validate the permalink's workspace, channel, root timestamp, known mapping,
   closed state, and actor authorization.
4. Persist control-message linkage and reopen the target atomically.
5. Post one idempotent acknowledgment in the control message's thread.
6. Poll the reopened target through `conversations.replies`.
7. Create at most one follow-up task from previously unseen actionable replies.

Because reopen requests are new roots, completed threads remain excluded from
routine reply polling and `reactions:read` is unnecessary.

## Configuration

Keep secrets out of TOML. Add non-secret Slack configuration owned by the Slack
channel feature. The exact model may use nested Pydantic types, but the operator
surface is:

```toml
[slack]
workspace_id = "T0123456789"
completion_reaction = "white_check_mark"

[[slack.channels]]
channel_id = "C0123456789"
repository = "dotfiles"
authorized_users = ["U0123456789"]
```

Validation must reject:

- Empty or malformed immutable IDs.
- Duplicate channel IDs.
- Unknown configured repository names.
- Duplicate channel/repository ambiguity.
- Empty or malformed reaction names.

`DaemonConfig` composes optional Slack feature configuration. Runtime Slack
code receives only Slack config and resolved repository policies, never the
whole `DaemonConfig`.

Add `OCINT_DAEMON_SLACK_BOT_TOKEN` to `DaemonSettings` as `SecretStr`. Only the
Slack client lifecycle factory unwraps it. Slack-disabled configuration does
not require the variable.

## Slack App Provisioning

Check in one Slack app manifest so the private-channel permissions are
reviewable:

- `bin/ocint/config/slack-app-manifest.yaml`

The manifest is the YAML definition pasted into Slack's **Create New App** ->
**From an app manifest** flow:

```yaml
_metadata:
  major_version: 1

display_information:
  name: ocint

features:
  bot_user:
    display_name: ocint
    always_online: false

oauth_config:
  scopes:
    bot:
      - groups:history
      - chat:write
      - reactions:write

settings:
  socket_mode_enabled: false
  token_rotation_enabled: false
```

Explicitly prohibit these scopes and features:

- `channels:read`
- `users:read`
- `reactions:read`
- `chat:write.public`
- Commands
- Event subscriptions
- Socket Mode

### Create The Slack App

1. Open [Slack Apps](https://api.slack.com/apps).
2. Select **Create New App**.
3. Select **From an app manifest**.
4. Select the Slack workspace that will contain the ocint channel.
5. Choose YAML and paste `bin/ocint/config/slack-app-manifest.yaml`.
6. Review the generated configuration before creation. Confirm that the bot
   scopes are exactly `groups:history`, `chat:write`, and `reactions:write`.
7. Confirm Socket Mode is disabled and there are no event subscriptions,
   commands, request URLs, or interactive features.
8. Select **Create**.
9. Open **OAuth & Permissions**.
10. Select **Install to Workspace** and approve the three requested scopes.
11. Return to **OAuth & Permissions** and copy the **Bot User OAuth Token**. It
    must begin with `xoxb-`. Do not place it in TOML, source control, terminal
    arguments, or documentation.

### Connect The Slack Channel

1. Open the target Slack channel.
2. Invite the bot explicitly:

   ```text
   /invite @ocint
   ```

3. Provision the copied `xoxb-` token through the hidden prompt:

   ```bash
   ocint daemon lch slack-token
   ```

   The command calls Slack's `auth.test` endpoint and prints the authenticated
   non-secret workspace ID, workspace name, bot user ID, and bot ID. Copy the
   returned `workspace_id` value beginning with `T`; do not try to obtain it
   from Slack workspace details.
4. In Slack, select **Copy link** on the private channel. The value immediately
   after `/archives/` is the immutable channel ID:

   ```text
   https://WORKSPACE.slack.com/archives/CHANNEL_ID
   ```

   Alternatively, open the channel in a browser. In a URL shaped like
   `https://app.slack.com/client/WORKSPACE_ID/CHANNEL_ID`, the first ID is the
   workspace and the second is the channel. Do not use the mutable channel
   name.
5. For each human who should be allowed to create or reopen tasks, open their
   Slack profile and select **More** -> **Copy member ID**. The copied immutable
   value begins with `U` or `W`. Do not use display names, email addresses, or
   the bot user ID returned by `auth.test`.
6. Paste those human member IDs into `authorized_users` and add the repository
   mapping to `daemon.toml`:

   ```toml
   [slack]
   workspace_id = "T0123456789"
   completion_reaction = "white_check_mark"

   [[slack.channels]]
   channel_id = "C0123456789"
   repository = "dotfiles"
   authorized_users = ["U0123456789", "W0123456789"]
   ```

   Every listed user may create root tasks and issue reopen requests in this
   configured channel. An unlisted user receives the unauthorized response. An
   empty list permits every human member of the channel.

7. Apply the updated configuration and verify credentials, workspace identity,
   bot identity, channel membership, and history access:

   ```bash
   ocint daemon lch apply
   ocint daemon doctor
   ```

8. If scopes are changed later, reinstall the Slack app to the workspace before
   rerunning `slack-token` and `doctor`.

The manual invite is intentional least privilege. Do not request
`chat:write.public` or channel discovery merely to avoid it.

## Credential Provisioning

Store the token with the existing daemon credentials in:

```text
$XDG_CONFIG_HOME/ocint/daemon.env
```

The managed assignment is:

```dotenv
OCINT_DAEMON_SLACK_BOT_TOKEN=xoxb-REDACTED
```

Add `ocint daemon lch slack-token`. It must:

1. Read the token through hidden stdin, never argv or normal output.
2. Reject empty values and non-`xoxb-` token shape before network access.
3. Validate `auth.test`, print only its non-secret workspace and bot identity,
   and, when Slack is already configured, require the configured workspace ID.
4. Atomically merge the assignment into `daemon.env`.
5. Preserve ownership and mode `0600`.
6. Render only `present`, `updated`, workspace ID, and non-secret status.

Replace setup's current reconstruction of `daemon.env` with a lossless
assignment merge. It must preserve:

- Existing API, GitHub, and Slack token assignments.
- Unknown assignments.
- Comments and blank lines.
- A final newline.

`lch setup` may discover/refresh GitHub as it does today but must never erase a
pre-provisioned Slack token. `lch apply` does not rewrite credentials and fails
clearly when Slack is configured without its token.

Update `SubprocessRunner` and all isolated discovery environments to strip
`OCINT_DAEMON_SLACK_BOT_TOKEN`. The token must not reach Git, validation,
OpenCode, attach, GitHub CLI, or unrelated subprocesses. It must not appear in
logs, exception text, config rendering, SQLite, or tests.

## Startup And Doctor

Slack-enabled daemon startup fails before readiness unless:

1. A Slack bot token exists.
2. `auth.test` succeeds.
3. The returned workspace ID matches configuration.
4. The bot user ID is non-empty and is persisted for agent classification.
5. Every configured channel permits `conversations.history?limit=1` with the
   configured token.

The channel probe verifies both scope and membership without requesting
`channels:read`. Private channels use their corresponding history method scope.

Extend `doctor` with redacted diagnostics:

- Environment-file safety and Slack token presence.
- Slack authentication status.
- Expected/actual workspace match by non-secret ID.
- Per-configured-channel access status by channel ID.
- Completion reaction configuration.

Never include token values or Slack message bodies. Slack diagnostics are
required only when Slack is configured.

## Tidy-First Delivery Sequence

### PR 1: Separate Channel And Execution Ownership

Changes:

- Add channel and execution domain packages.
- Move code without changing external behavior.
- Split `GitHubService` into GitHub issue channel and GitHub PR publisher.
- Introduce narrow shared GitHub transport with capability-specific clients.
- Update CLI composition, facades, tests, and Tach.
- Keep the current schema and GitHub behavior unchanged.
- Retain the existing publication-origin persistence temporarily; PR 2 removes
  that coupling when it can migrate ownership safely.

Why first:

- Slack can then be added as a channel rather than another branch in a combined
  GitHub service.
- PR publication no longer depends on the conversation implementation.

Tests:

- Existing execution unit tests pass after movement.
- Existing GitHub E2E behavior remains unchanged.
- Separate tests prove issue observation/reply and PR publication can be
  constructed and exercised independently over one injected transport.
- Tach proves tasks do not import concrete providers.

### PR 2: Introduce Typed Channel Identity And Publication Ownership

Changes:

- Add provider-neutral typed actor/thread/message identities.
- Change tasks, jobs, repositories, and APIs to use them.
- Add channel and publication ownership schema.
- Remove `ThreadOrigin` and other channel-specific values from publication.
- Backfill current GitHub data non-destructively.
- Remove obsolete columns only after migration assertions pass.

Why second:

- Slack must not inherit GitHub login semantics or opaque concatenated IDs.
- Slack-originated work needs PR ownership independent of GitHub issues.

Tests:

- Migration fixture from the current head preserves jobs and all task links.
- Existing queued/running/completed jobs load after upgrade.
- Existing GitHub issue/comment identities resolve correctly.
- Existing owned PR mappings produce publication owner rows.
- A publisher test proves `PublicationRequest` accepts no channel-specific
  origin and works for both GitHub- and Slack-derived owner keys.
- Upgrade, downgrade where representable, and re-upgrade retain invariants.

### PR 3: Add Slack Boundary And Least-Privilege Configuration

Changes:

- Add Slack config, validated IDs, API DTOs, client, and facade.
- Add the private-channel Slack app manifest.
- Implement `auth.test`, workspace validation, channel access probes, cursor
  pagination primitives, and 429 modeling.
- Compose optional Slack lifecycle in CLI without message ingestion yet.

Why third:

- Validate the external boundary and security contract before workflow logic.

Tests:

- Config rejects malformed/duplicate IDs and unknown repositories.
- Integration server verifies bearer header and request shapes.
- `auth.test` mismatch and inaccessible channels fail before readiness.
- Cursor pagination and `Retry-After` parse to typed outcomes.
- The manifest contains exactly the approved scopes and no event configuration.

### PR 4: Add Durable Slack Polling And Ingestion

Changes:

- Add Slack schema and repository.
- Poll channel history and open-thread replies.
- Persist every page, cursor, watermark, retry time, and provider mapping.
- Derive titles and classify authorized, unauthorized, and bot messages.
- Feed Slack observations through the normal task coordinator.

Why fourth:

- Delivers restart-safe input before adding completion side effects.

Tests:

- Authorized root creates one initial task.
- First non-empty line is title; complete body remains in prompt.
- Authorized reply creates one follow-up and reuses execution context.
- Unauthorized messages cannot schedule work.
- Bot output is `AGENT_RESPONSE` and cannot loop.
- Repeated polls do not duplicate messages or tasks.
- Restart mid-pagination resumes without gaps.
- 429 defers future polls without sleeping.

### PR 5: Add Completion, Closure, And Reopening

Changes:

- Make completion text provider-neutral and domain-owned.
- Implement idempotent Slack reply, reaction, and closure checkpoints.
- Exclude closed roots from reply polling.
- Implement explicit top-level permalink reopening and acknowledgments.
- Preserve closed-owned-PR refusal through the originating channel.

Why fifth:

- Completes Slack behavior while bounding future polling.

Tests:

- Completion posts one reply, one reaction, and closes the root.
- Restart between completion steps resumes without duplicate effects.
- Closed roots are not passed to `conversations.replies`.
- Valid reopen reactivates one known root and ingests missed replies once.
- Invalid and unauthorized reopen requests are idempotently rejected.
- GitHub and Slack receive the same shared completion/refusal text.
- Closed owned PR does not create a replacement.

### PR 6: Add LCH Credential Provisioning And Diagnostics

Changes:

- Add Slack `SecretStr` setting.
- Add lossless environment-file merge.
- Add hidden-input `lch slack-token`.
- Preserve Slack credentials through setup/apply flows.
- Strip Slack token from subprocess environments.
- Add redacted doctor checks.

Why sixth:

- Makes the feature safely operable without manual unsafe secret handling.
- This can proceed after PR 3 in parallel with polling work if kept isolated.

Tests:

- Existing comments, blank lines, unknown assignments, and all credentials
  survive merge.
- Token replacement changes only the Slack assignment.
- File remains a user-owned regular mode-0600 file.
- Token is absent from every unrelated child environment.
- Doctor reports presence/auth/access without rendering token values.
- Slack-disabled installs do not require a Slack token.

### PR 7: Documentation, Live Smoke, And Rollout

Changes:

- Update daemon architecture, configuration, workflow, operations, security,
  and package index documentation.
- Update example TOML and daemon schema smoke assertion.
- Document Slack app creation, invites, IDs, token provisioning, completion,
  reopening, rate limits, rotation, rollback, and troubleshooting.
- Add an opt-in live Slack smoke test or executable manual runbook.

Tests:

- Example TOML validates.
- The app manifest parses and has the exact private-channel scopes.
- Daemon schema smoke expects the new tables.
- Full package test/check/smoke commands pass.

## Test Strategy

### Unit Tests

Use stateful fakes, not mocks, for:

- Slack history/reply pages.
- Slack reply/reaction outcomes.
- Rate limits and transient failures.
- Multi-channel dispatch.
- Task completion and reopening transitions.
- Credential-file merge behavior.

Follow GIVEN/WHEN/THEN and test one observable behavior per test. Keep fixtures
in the nearest owning module; do not add general test helper modules.

### Integration Tests

Use a local HTTP server for Slack transport behavior:

- Authorization header without leaking its value.
- `auth.test` validation.
- History/replies request parameters.
- Cursor pagination.
- Slack `{ "ok": false }` errors.
- HTTP 429 and `Retry-After`.
- `chat.postMessage` thread routing.
- `reactions.add` and `already_reacted`.

Use Alembic integration fixtures for migration and restart behavior. Include a
pre-change database with GitHub issues/comments, addressed and unresolved tasks,
multiple task attempts, completed jobs, and an owned PR.

### E2E Tests

Retain `tests/e2e/ocint/daemon/test_github.py` behavior after the split. Add the
Slack counterpart covering:

- Initial root request.
- Unauthorized actor.
- Failed execution plus new follow-up.
- Session/worktree/branch reuse.
- Completion reply and reaction.
- Agent response exclusion.
- Duplicate polling.
- Closure and explicit reopen.
- Closed owned PR refusal.
- Restart recovery.

Shared behavior belongs in domain tests; adapter E2E tests verify translation
and provider effects rather than duplicating implementation assertions.

### Architecture Tests

Use Tach for dependency direction. Keep behavior tests for facade import safety
and public exports where they represent a supported contract. Do not add AST
tests for rules Tach can express.

### Live Slack Smoke

The live test is opt-in and requires only environment-provided disposable
credentials and IDs. It must not delete messages or channels automatically.

Manual acceptance sequence:

1. Start with a disposable configured channel and open PR-capable repository.
2. Post an authorized root request.
3. Wait for the next daemon cycle.
4. Confirm one PR, one Slack thread response, and one completion reaction.
5. Confirm a later daemon cycle does not poll the closed thread.
6. Add a follow-up while closed and confirm it does not run.
7. Post `reopen <root permalink>` as a new root.
8. Confirm one follow-up reuses the original session/worktree/branch/PR.
9. Confirm a second cycle creates no duplicate task, reply, or reaction.

No live secret, workspace ID, channel ID, user ID, or message body is committed
to fixtures or logs.

## Failure And Idempotency Policy

- Slack authentication/workspace/channel access failure: fail startup before
  readiness.
- Slack 429: persist `retry_not_before`, end Slack polling for this cycle, and
  retry on a later timer invocation.
- Slack network/5xx failure: retain cursor/checkpoint and fail the current
  operation visibly.
- Duplicate history/reply item: provider identity uniqueness returns existing
  persistence state.
- Duplicate completion reply: delivery key returns the recorded Slack message.
- Duplicate reaction: `already_reacted` is success.
- Crash after external reply but before local checkpoint: reconcile using the
  delivery intent plus a deterministic bot-reply lookup before posting again.
  The exact lookup mechanism must be proven by test because Slack does not
  support GitHub-style hidden comment markers.
- Invalid reopen: preserve target state and send one keyed explanatory response.
- Bot-authored message: persist as agent output and never schedule it.
- Closed/merged owned PR: refuse replacement and notify the originating channel.
- Slack disabled: no token requirement, API call, schema polling, or diagnostic
  failure.

## Documentation Updates

Update:

- `bin/ocint/ocint/daemon/README.md`: Slack is no longer an intentional absence.
- `bin/ocint/docs/daemon/architecture.md`: channel/task/execution boundaries and
  dependency graph.
- `bin/ocint/docs/daemon/configuration.md`: Slack IDs, mappings, reaction, token.
- `bin/ocint/docs/daemon/workflow.md`: root request, completion, and reopen.
- `bin/ocint/docs/daemon/operations.md`: polling, 429, access, and recovery.
- `bin/ocint/docs/daemon/security.md`: Slack credential boundary and scopes.
- `bin/ocint/config/daemon.example.toml`: non-secret Slack example.
- Slack app manifest: private-channel least-privilege setup.

Security documentation must show that only the Slack client receives the Slack
token and that OpenCode, validation, Git, GitHub, attach, and subprocess tools do
not inherit it.

## Rollout

1. Merge and install the domain split with Slack disabled.
2. Migrate an existing daemon database and verify GitHub parity after restart.
3. Merge typed identity/publication ownership migration and verify existing PR
   reuse/refusal.
4. Create the internal Slack app from the checked-in private-channel manifest.
5. Install the app and manually invite the bot to the target channel.
6. Run `ocint daemon lch slack-token`, enter the `xoxb-` token through the
   hidden prompt, and record the workspace ID returned by `auth.test`.
7. Add that workspace ID plus the channel/user IDs and repository mapping to
   `daemon.toml`.
8. Run `ocint daemon lch apply`.
9. Run `ocint daemon doctor` and require every Slack check to pass.
10. Perform the live root/completion/closed/reopen smoke sequence.
11. Enable additional channels one at a time.

Rollback must disable Slack configuration without removing Slack tables or
credentials automatically. Existing GitHub processing and persisted Slack state
remain intact for a later re-enable. Revoke the Slack token in Slack when the
integration is intentionally retired.

## Verification Commands

Baseline and focused tests:

```bash
uv run --directory /home/vikram_orbio_earth/personal/dotfiles-wt2 --package ocint --frozen pytest /home/vikram_orbio_earth/personal/dotfiles-wt2/bin/ocint/tests/e2e/ocint/daemon/test_github.py
uv run --directory /home/vikram_orbio_earth/personal/dotfiles-wt2 --package ocint --frozen pytest /home/vikram_orbio_earth/personal/dotfiles-wt2/bin/ocint/tests/unit/ocint/daemon/tasks
uv run --directory /home/vikram_orbio_earth/personal/dotfiles-wt2 --package ocint --frozen pytest /home/vikram_orbio_earth/personal/dotfiles-wt2/bin/ocint/tests/unit/ocint/daemon/lch
```

After Slack tests exist, run their canonical mirrored paths:

```bash
uv run --directory /home/vikram_orbio_earth/personal/dotfiles-wt2 --package ocint --frozen pytest /home/vikram_orbio_earth/personal/dotfiles-wt2/bin/ocint/tests/unit/ocint/daemon/channels/slack
uv run --directory /home/vikram_orbio_earth/personal/dotfiles-wt2 --package ocint --frozen pytest /home/vikram_orbio_earth/personal/dotfiles-wt2/bin/ocint/tests/integration/ocint/daemon/channels/test_slack.py
uv run --directory /home/vikram_orbio_earth/personal/dotfiles-wt2 --package ocint --frozen pytest /home/vikram_orbio_earth/personal/dotfiles-wt2/bin/ocint/tests/e2e/ocint/daemon/test_slack.py
```

Architecture and complete package verification:

```bash
just --justfile /home/vikram_orbio_earth/personal/dotfiles-wt2/bin/ocint/justfile tach
just --justfile /home/vikram_orbio_earth/personal/dotfiles-wt2/bin/ocint/justfile test
just --justfile /home/vikram_orbio_earth/personal/dotfiles-wt2/bin/ocint/justfile check
just --justfile /home/vikram_orbio_earth/personal/dotfiles-wt2/bin/ocint/justfile smoke-daemon
```

Do not add a live marker command to default CI. Document its exact environment
and invocation only after the live test shape exists.

## Risks And Mitigations

### Migration Risk

Typed identity touches durable core tables. Mitigate with copy-and-verify
migrations, preserved primary keys, realistic pre-head fixtures, foreign-key
checks, and GitHub restart E2E coverage. Never use the prior destructive reset
pattern.

### Slack Polling Cost

Polling every historical thread would exhaust request budgets. Persist channel
watermarks, poll replies only for open roots, close on completion, and reopen via
a newly discoverable root control message.

### Slack Reply Duplication

Slack lacks hidden deterministic markers equivalent to GitHub comments. Persist
delivery intent before posting, resulting timestamp after posting, and test the
crash window explicitly. If Slack message metadata can provide a stable
application idempotency marker without new scopes, evaluate it during transport
implementation; do not claim exactly-once behavior without proving recovery.

### Credential Loss

Current setup reconstructs `daemon.env` from known values. Replace this before
relying on a Slack assignment, and test preservation of comments, unknown
assignments, and all managed secrets.

### Provider Leakage

Composite strings and `GitHubLogin` currently cross domain boundaries. Parse
typed values at adapters, move authorization policy to each channel, and enforce
imports with Tach.

### Scope Creep

Do not add DMs, multi-workspace OAuth, channel discovery, files, edits,
reactions-based reopen, Events API, Socket Mode, slash commands, or a dynamic
plugin registry in this work.

## Completion Criteria

- Existing GitHub issue E2E behavior passes after module movement and migration.
- Existing jobs, tasks, messages, attempts, and owned PRs survive upgrade.
- GitHub issue channel and GitHub PR publication are independent capabilities.
- Publication accepts no channel-specific origin.
- Slack startup validates token, workspace, bot identity, and channel access.
- An authorized Slack root creates exactly one task and GitHub PR.
- Slack receives no duplicate completion response or root reaction across all
  tested retry and crash windows.
- Completed Slack roots are excluded from reply polling.
- Explicit permalink reopening creates at most one follow-up and reuses prior
  execution context and PR ownership.
- Unauthorized users and bot messages cannot schedule work.
- Pagination, restart, and rate limiting are durable and tested.
- The Slack manifest contains only approved private-channel scopes and no event
  configuration.
- Slack token provisioning is hidden, mode-0600, lossless, redacted, and isolated
  from unrelated subprocesses.
- Tach, full tests, static checks, and daemon smoke all pass.
- Operator documentation contains executable provisioning, rollout, rollback,
  troubleshooting, and live-smoke instructions.
