# Daemon Operations

`ocint daemon lch` is the operator surface for a daemon installed through the
Linux user-systemd lifecycle.

## Commands

```text
setup            create initial configuration and install all four units
slack-token      validate and atomically install a hidden-input Slack bot token
apply            provision coordinator policy/auth and regenerate all four units
lifecycle        show timer, job service, coordinator, ngrok, and log state
list             list recent durable jobs from SQLite
status JOB_ID    show one durable job
attach JOB_ID    attach to that job's live OpenCode session
logs             read or follow private rotating logs
uninstall        remove only the generated user units
```

`list` and `status` read the daemon database directly, so they work while the
bounded service is inactive and do not require API credentials.

`ocint daemon doctor` is the preflight surface. It validates private config and
environment files, required credentials, Slack `auth.test` and channel access,
ngrok v3 and its static URL, exact OpenCode `1.18.15`, both isolated OpenCode
policies/data homes, coordinator workspace state, four distinct loopback ports,
migration head, user lingering, and exact systemd payloads. Workspace context
and the migration revision may be pending until first coordinator/timer startup.
Coordinator and ngrok may be disabled during pre-rollout doctor checks.

## Command Outcomes

Every LCH command emits data-bearing output. Mutation commands identify the
artifact, outcome, path, and whether configuration changed; they never print a
bare `done` or silently reuse configuration.

```text
Configuration: reused; path=~/.config/ocint/daemon.toml; modified=no
Systemd service: regenerated; path=~/.config/systemd/user/ocint-daemon.service; executable=...
Systemd timer: enabled; path=~/.config/systemd/user/ocint-daemon.timer; inactive_interval_seconds=600
Systemd coordinator services: regenerated; coordinator=...; ngrok=...; enabled=no
```

Secrets are always redacted. Read-only commands return the requested lifecycle,
job, attachment, or log data instead of a generic success message.

`slack-token` accepts the token only through Click's hidden prompt. Piped stdin
supports automation; the token never appears in argv or command output. Existing
comments, unknown assignments, and API/GitHub tokens in `daemon.env` are
preserved byte-for-byte except for the selected assignment.

```text
 daemon.sqlite
      |
      +--> lch list
      `--> lch status JOB_ID
```

## Inspect Jobs

```bash
ocint daemon lch list
ocint daemon lch list --limit 25
ocint daemon lch status JOB_ID
```

The list shows the 10 newest jobs by default. `--limit N` selects any positive
number of recent jobs. It keeps full IDs copyable and includes each job's state,
stage, and canonical work title. Detailed status includes the full title,
repository, actor, session, worktree, branch, commit, pull request, and error.

## Attach

```bash
ocint daemon lch attach JOB_ID
```

Attachment requires a currently running job with a provisioned OpenCode session.
The command behaves like `opencode attach`: it inherits the terminal and remains
interactive until OpenCode exits. LCH fixes the URL, directory, and session from
the durable job, so it intentionally accepts no OpenCode options.

```text
lch attach JOB_ID
      |
      +--> read API token from private daemon.env
      +--> request live attachment metadata over loopback
      +--> receive ephemeral OpenCode credentials in memory
      `--> opencode attach URL --dir WORKTREE --session SESSION
```

See [`security.md`](security.md) for the authentication boundary.

## Lifecycle, Status, And Logs

```bash
ocint daemon lch lifecycle
ocint daemon lch logs --lines 200
ocint daemon lch logs --follow
```

The lifecycle view reports installation, timer schedule, service result, and log
path, plus coordinator/ngrok active and unit-file states. Job status remains
`ocint daemon lch status JOB_ID`. For raw service detail, use:

```bash
systemctl --user status ocint-daemon.timer --no-pager
systemctl --user status ocint-coordinator.service --no-pager
systemctl --user status ocint-coordinator-ngrok.service --no-pager
```

Logs are read directly rather than through journald and continue across
rotation.

## Safe Coordinator Rollout

The initial `setup` installs coordinator units without enabling them and enables
only the existing GitHub timer. Later `setup` and `apply` runs preserve each
coordinator unit's current enablement and report the actual unit-file states;
they never silently disable an already enabled production coordinator. Disable
both units explicitly when an inspection or live-test window is required.

```text
setup/apply
   |
   +-> provision and inspect policy/auth
   +-> verify timer-driven GitHub daemon
   +-> initial install: coordinator + ngrok disabled
   +-> later apply: preserve and report current enablement
   |
   `-> live E2E passes -> enable coordinator -> enable ngrok
```

Use this order:

```bash
ocint daemon lch apply
ocint daemon doctor
ocint daemon lch lifecycle

systemctl --user disable --now ocint-coordinator-ngrok.service
systemctl --user disable --now ocint-coordinator.service
# Run the autonomous live E2E below.

systemctl --user enable --now ocint-coordinator.service
systemctl --user enable --now ocint-coordinator-ngrok.service
ocint daemon lch lifecycle
ocint daemon doctor
```

The GitHub timer can remain enabled throughout. Timer/coordinator startup owns
the serialized migration; do not hide that startup check with a manual migrate.
Start coordinator first so it generates context from the final validated
repository projection and ingress/OpenCode become healthy before the static
tunnel accepts callbacks.

### Autonomous Live Slack E2E

The live harness is marked `live` under the normal test hierarchy. Strict marker
registration and the default `-m 'not live'` deselect it from `pytest` and
`just test`. Invoke it explicitly from the repository workspace after confirming
the two production units are disabled:

```bash
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
set -a
. "$CONFIG_HOME/ocint/daemon.env"
. "$CONFIG_HOME/ocint/live-e2e.env"
set +a
uv run --directory /home/vikram_orbio_earth/personal/dotfiles-wt \
  --package ocint --frozen pytest -m live -s \
  bin/ocint/tests/live/ocint/daemon/coordinator/test_slack.py
```

The **ocint E2E actor** app was created from
[`../../config/slack-e2e-actor-manifest.yaml`](../../config/slack-e2e-actor-manifest.yaml),
in the production app's workspace. Grant user OAuth `chat:write`, reinstall the
app, and store the authorized test user's xoxp token only in the mode-0600
`live-e2e.env` shown above. That user must be in the configured public channel
and its `authorized_users`.

No person posts or clicks during this test. The harness posts a uniquely marked
root through the authorized user's Slack client with a
`client_msg_id`. Slack sends a signed app-authored `message.channels` event with
the same authorized user plus actor `bot_id` and `app_id` through the static
ngrok URL. A one-probe test-only classifier accepts only the exact configured
workspace, channel, user, UUID, and prompt; exact Slack retries remain accepted
for durable deduplication. The production classifier remains unchanged. The
real restricted OpenCode `1.18.15`
coordinator runs; and the production bot returns the answer to the same Slack
thread. That reply is ignored normally as bot-authored input. Callback
diagnostics contain status codes, never request bodies or credentials.

Probe-scoped durable rows must contain the real event, conversation, OpenCode
session ID, assistant message ID, response, and delivery receipts. The Slack
reply must include the probe ID and the `dotfiles` catalogue entry. The harness
also proves that no task, job, worktree, Git operation, or GitHub publication
was created. It stops only processes it started and leaves the marked Slack
thread and durable rows as evidence. Enable the production coordinator and
ngrok units afterward, once harness-owned processes have exited and the
evidence has been inspected.

### Restart And Rollback

Restart coordinator before ngrok so the local receiver is ready when the tunnel
reconnects:

```bash
systemctl --user restart ocint-coordinator.service
systemctl --user restart ocint-coordinator-ngrok.service
ocint daemon lch lifecycle
```

The coordinator unit uses `KillMode=mixed`, so restart first asks the main
process to shut down rather than signaling its OpenCode child concurrently.
Handlers are active before OpenCode starts, so a stop during startup cancels and
closes the child before returning normally. A graceful coordinator stop emits
this lifecycle sequence:

```text
Coordinator bounded shutdown started
Coordinator bounded shutdown completed
Coordinator OpenCode shutdown started
Coordinator OpenCode shutdown completed
```

`Coordinator OpenCode child exited` during that sequence indicates an
unexpected child exit rather than the expected restart path.

Accepted events, prompt intents, full responses, chunks, and retry deadlines
are durable. Restart resumes incomplete work in source order and reconciles
uncertain OpenCode prompts and Slack posts. Retryable OpenCode processing stops
after the configured number of retries following its initial attempt, delivers
the safe failure response, and releases the next ordered turn. Slack delivery
retries do not consume that budget and continue with the persisted response.

For rollback, stop the public path first while keeping the GitHub timer
operational:

```bash
systemctl --user disable --now ocint-coordinator-ngrok.service
systemctl --user disable --now ocint-coordinator.service
ocint daemon lch lifecycle
```

Preserve the shared database and all coordinator rows, generated workspace,
OpenCode data, private environment, ngrok configuration, and Slack evidence.
Disable Slack Event Subscriptions in the Slack app only for a prolonged
rollback.

## Failure Handling

- Invalid actors and repositories fail before persistence.
- Job timeout records `job timed out`.
- Validation failure prevents commit and push.
- Git failure prevents publication.
- GitHub failure leaves the durable stage available for inspection.
- A closed or merged owned pull request is reported and never replaced.
- Attach returns a conflict when the job has no live session.
- Invalid or stale Slack signatures are rejected without coordinator work.
- A database ingress failure returns 5xx so Slack retries.
- Slack 429 and transient delivery failures retain durable retry deadlines.
- Coordinator restart resumes incomplete turns and deliveries in order.

Subprocess output is bounded by `command_output_bytes`. Timed-out managed
commands are terminated as process groups.

## Troubleshooting

### Service is not running

The job service is normally inactive between timer invocations. The coordinator
and ngrok services should be active only after rollout. Check all lifecycle
states and the last result:

```bash
ocint daemon lch lifecycle
ocint daemon lch logs --lines 200
ocint daemon doctor
```

### Job remains queued

Inspect the lifecycle and logs. Queued jobs are scheduled at startup; rows
inserted externally after startup are intentionally not polled.

### Slack does not receive a reply

Check `lch lifecycle`, doctor, and logs. Confirm both coordinator units are
active, the static URL ends in `/slack/events` in Slack configuration,
`message.channels` is subscribed, the bot belongs to the public channel, and the
human member ID is authorized. A 5xx causes Slack to retry; a `200` means the
event disposition was committed, including ignored and duplicate outcomes.

### Job failed validation

Use `lch status JOB_ID`, then run the configured check from the retained
worktree. Validation failures do not commit or push.

### Attach fails

Confirm the job is `running`, has a session and worktree, and the service is
active. Completed, failed, queued, and stale sessions are not attachable.

### Git authentication fails

Run `ocint daemon doctor`. Network Git uses one explicit mode-0600 identity,
strict host checking, and no SSH-agent fallback.

### OpenCode reports a lock

Confirm the service uses its isolated `xdg_data_home` and that managed
`auth.json` is a symlink. It must not share the interactive OpenCode database.

### Logs cannot be read

Use `lch lifecycle` to confirm the path. The directory must be user-owned mode
0700, and active and rotated files must be regular user-owned mode-0600 files.
