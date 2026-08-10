# Daemon Configuration

Initial setup discovers repository-specific values and writes private managed
configuration. The default path is `$XDG_CONFIG_HOME/ocint/daemon.toml`, falling
back to `~/.config/ocint/daemon.toml`. `OCINT_DAEMON_CONFIG` overrides it.

The tracked schema example is [`../../config/daemon.example.toml`](../../config/daemon.example.toml).

## Setup And Ownership

Before first setup, install/authenticate ngrok and make the assigned static base
URL available either in the private daemon environment file or in the setup
shell as `OCINT_NGROK_URL`. Then run setup from the target Git checkout:

```bash
export OCINT_NGROK_URL=https://YOUR_STATIC_NGROK_DOMAIN
ocint daemon lch setup
ocint daemon migrate
ocint daemon doctor
```

`daemon.toml` becomes user-owned after its first creation. Command behavior is
deliberately asymmetric:

```text
daemon.toml absent  -> setup discovers values and creates it
daemon.toml exists  -> setup reuses it byte-for-byte
apply               -> reads it and regenerates systemd units only
package reinstall   -> does not read or modify it
uninstall           -> preserves it and all daemon state
```

Initial setup leaves coordinator and ngrok disabled. Regeneration does not
change their current enablement: later setup/apply reports and preserves each
unit-file state.

Defaults apply only when `setup` first creates the file. Changing a default in
Python does not migrate an explicit value already stored in `daemon.toml`. Edit
the TOML and run the following command to apply lifecycle changes:

```bash
ocint daemon lch apply
```

Discovery validates every input before its first write:

```text
 target checkout
   +-- isolated effective Git config --------> one push URL + owner/repository
   +-- gh api --hostname github.com user ----> login
   +-- gh repo view OWNER/REPOSITORY --------> canonical repo + default branch
   +-- gh auth token --hostname github.com --> token presence/value for env only
   +-- effective Git author -----------------> name/email
   +-- safe core.sshCommand + ssh -G --------> executable/key/known-hosts
   `-- XDG OpenCode config/auth -------------> model/provider + auth source
             |
             v
 validate remote equality, credentials, policy, ports, paths, linger, units
             |
             v
 atomically write managed files; auth remains a symlink
```

Setup never starts OAuth or device login. It discovers the GitHub token with
`gh auth token --hostname github.com`, preserves an existing daemon API token,
requires ngrok v3 and the static URL, and installs the systemd units. Add the
Slack bot token and signing secret before expecting doctor to pass. A later
setup reuses the existing TOML without running discovery again.

## Slack Coordinator

Slack is an Events API input to the Phase 1 coordinator, not a polling source
for repository jobs. The coordinator section is required and names one Slack
workspace plus the public channels and human member IDs allowed to converse:

```toml
[coordinator]
workspace_root = "~/.local/share/ocint/coordinator"
turn_timeout_seconds = 1800
shutdown_timeout_seconds = 30
orphan_retention_seconds = 86400
retry_seconds = 5
max_turn_retries = 3
response_chunk_characters = 3500
slack_post_interval_seconds = 1

[coordinator.ingress]
host = "127.0.0.1"
port = 8733
max_request_bytes = 65536
timestamp_tolerance_seconds = 300
processing_timeout_seconds = 2.5
database_busy_timeout_ms = 2000

[coordinator.slack]
workspace_id = "T01234567"

[[coordinator.slack.channels]]
channel_id = "C01234567"
authorized_users = ["U01234567"]

[coordinator.opencode]
server_url = "http://127.0.0.1:4098"
username = "opencode"
request_timeout_seconds = 30
expected_version = "1.18.15"
executable = "/usr/bin/opencode"
config_file = "~/.config/ocint/coordinator-opencode-xdg/opencode/opencode.json"
xdg_config_home = "~/.config/ocint/coordinator-opencode-xdg"
xdg_data_home = "~/.local/share/ocint/coordinator-opencode-data"
startup_timeout_seconds = 120
shutdown_timeout_seconds = 10
```

`authorized_users` contains Slack member IDs, not display names. Channel IDs
must be unique, every authorized-user set must be non-empty, and the configured
workspace must match Slack `auth.test`. Only configured human actors can create
turns. Bot messages, including coordinator replies, are durably ignored so the
bot cannot start a reply loop.

`max_turn_retries` counts retry schedules after the initial turn attempt. The
default `3` therefore allows at most four OpenCode processing attempts: the
initial attempt plus three retries. If the fourth attempt still reports a
retryable provider error or an inactive incomplete prompt, the coordinator
persists and delivers `safe_failure_text` and makes the next ordered turn
eligible. Slack delivery retries are not counted against this budget; they
remain unbounded and always resume the already persisted response.

Each Slack root maps to one coordinator OpenCode session. A thread reply reuses
that session. The coordinator reads only a generated fake/context workspace:

```text
~/.local/share/ocint/coordinator/
├── AGENTS.md
└── repositories.json
```

`repositories.json` is projected from the existing `[[repositories]]` registry
and contains only `name`, `description`, `github_repository`, and
`default_branch`. It is a catalogue, not a target checkout. Do not put local
paths, credentials, remotes, author identities, or validation commands in it.

Create the Slack app from
[`../../config/slack-app-manifest.yaml`](../../config/slack-app-manifest.yaml).
It requests exactly `channels:history` and `chat:write`. Socket Mode, slash
commands, reactions, file uploads, and private-channel history are not used.
This is the production `ocint daemon` app; it receives events and delivers
coordinator replies.

### Enable Events API Delivery

Open [Your Slack Apps](https://api.slack.com/apps), select **ocint**, and
configure the existing app:

1. Open **Basic Information > App Credentials**. Copy the **Signing Secret** to
   `OCINT_DAEMON_SLACK_SIGNING_SECRET` in the private mode-0600
   `$XDG_CONFIG_HOME/ocint/daemon.env` file.
2. Open [**Event Subscriptions**](https://api.slack.com/apps/A0BLGK5EY56/event-subscriptions?) and turn **Enable Events** on.
3. Set **Request URL** to the configured `OCINT_NGROK_URL` followed by
   `/slack/events`.
4. Wait for Slack to mark the Request URL as **Verified**. Slack sends a signed
   `url_verification` request to perform this check.
5. Under **Subscribe to bot events**, add `message.channels` for configured
   public channels.
6. Save the changes and reinstall the app to the workspace if Slack requests
   it.

Use an ngrok static HTTPS domain. Store its base URL only in the private
`daemon.env`; do not include `/slack/events` in the variable. Display the final
Request URL without writing the domain into tracked configuration:

```bash
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
set -a
. "$CONFIG_HOME/ocint/daemon.env"
set +a
printf '%s/slack/events\n' "$OCINT_NGROK_URL"
```

The bot must be a member of each configured public channel. The Events API
request URL is public, but every callback must pass Slack signature verification
before the daemon accepts it.

The inbound contract parses both Slack `channel_type="channel"` and
`channel_type="group"` message variants through a normal typed union. Phase 1
deploys only public channels: private `message.groups` subscription and
`groups:history` scope are intentionally not configured.

### Create The Live E2E Actor

The autonomous live test uses a second app named **ocint E2E actor**. It was
created from
[`../../config/slack-e2e-actor-manifest.yaml`](../../config/slack-e2e-actor-manifest.yaml)
in the same workspace. Add the user OAuth `chat:write` scope and reinstall the
app so it issues a User OAuth Token for the test user. The installing user must
be a member of the public E2E channel and its Slack member ID must appear in
that channel's `authorized_users` configuration.

The app retains its existing bot `chat:write` scope to match the installed app,
but that bot identity is not the test sender and is unused by E2E. The app has
no Events API subscriptions, Socket Mode, or interactivity. The User OAuth
client posts an app-authored root carrying the authorized `user` plus `bot_id`,
`app_id`, and the exact UUID `client_msg_id`. The harness injects an exact,
one-probe classifier in test composition; production continues rejecting every
bot/app-authored event.

Store the test-only User OAuth Token in a separate private file, using
[`../../config/live-e2e.env.example`](../../config/live-e2e.env.example):

```bash
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
cp bin/ocint/config/live-e2e.env.example "$CONFIG_HOME/ocint/live-e2e.env"
chmod 600 "$CONFIG_HOME/ocint/live-e2e.env"
vi "$CONFIG_HOME/ocint/live-e2e.env"
```

Set only `OCINT_E2E_SLACK_ACTOR_USER_TOKEN`. Never put it in `daemon.env`;
production systemd units do not load `live-e2e.env`. Neither setup nor doctor
requires this live-test-only credential.

Install or rotate the bot token without putting it in argv:

```bash
ocint daemon lch slack-token
# automation:
printf '%s\n' "$SLACK_TOKEN" | ocint daemon lch slack-token
```

The hidden prompt validates `auth.test`, required scopes, and the configured
workspace before atomically updating `daemon.env`. Add the Slack signing secret
and ngrok base URL separately; neither belongs in TOML or a package `.env` file.

```bash
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
vi "$CONFIG_HOME/ocint/daemon.env"
# Set exactly one non-empty assignment for each:
# OCINT_DAEMON_SLACK_SIGNING_SECRET=...
# OCINT_NGROK_URL=https://YOUR_STATIC_NGROK_DOMAIN
chmod 600 "$CONFIG_HOME/ocint/daemon.env"
```

The ngrok account authtoken is different: keep it in ngrok's private config via
`ngrok config add-authtoken`, not in `daemon.env`. The coordinator systemd unit
loads `daemon.env`; the ngrok unit receives only its public URL and reads its own
credential configuration. Neither OpenCode child receives Slack or ngrok
credentials.

## Root Settings

| Setting | Meaning |
| --- | --- |
| `database_path` | Shared daemon SQLite database for GitHub jobs and coordinator state |
| `mirror_root` | Managed bare Git mirrors |
| `worktree_root` | Managed per-job worktrees |
| `repositories` | Allowed repository registry |
| `idle_timeout_seconds` | Unchanged idle grace before shutdown |

Mirror and worktree roots must differ.

## Repository Settings

| Setting | Meaning |
| --- | --- |
| `name` | Stable local repository name |
| `description` | Safe coordinator-catalogue description |
| `remote_url` | SSH remote; HTTP and local paths are rejected |
| `default_branch` | Base branch for worktrees and pull requests |
| `github_repository` | GitHub `owner/repository` |
| `author_name`, `author_email` | Explicit commit identity |
| `actors` | Optional GitHub login allowlist |
| `checks` | Validation commands run in order |

Repository names are unique. An empty actor set permits any authenticated GitHub
actor. Network Git always uses the configured SSH identity and known-hosts file.
Issue titles must follow the target repository's commit and pull-request title
convention. The daemon canonicalizes them with one case-insensitive `ocint:`
prefix before persistence and publication.

## Scheduler And Lifecycle

| Setting | Default | Meaning |
| --- | ---: | --- |
| `scheduler.capacity` | `1` | Concurrent in-process jobs |
| `scheduler.job_timeout_seconds` | `3600` | Maximum job duration |
| `scheduler.shutdown_timeout_seconds` | `30` | Active-job shutdown grace |
| `scheduler.command_timeout_seconds` | `600` | Git and validation timeout |
| `scheduler.command_output_bytes` | `65536` | Error-output limit |
| `lifecycle.startup_delay_seconds` | `60` | Delay after user-manager startup |
| `lifecycle.inactive_interval_seconds` | `600` | Delay after one invocation exits |

Capacity uses an `asyncio.Semaphore`; there is no scheduler polling loop.

## OpenCode, Ports, API, And Logging

Both runtimes start exactly the configured OpenCode executable and require
version `1.18.15`; a mismatch fails startup. They use different loopback ports
and isolated XDG data/config homes. The job runtime receives the unattended job
policy. The coordinator receives a stricter policy and the fake/context
workspace only.

```text
timer job OpenCode       127.0.0.1:4097
timer control API        127.0.0.1:8732
coordinator OpenCode     127.0.0.1:4098
Slack Events ingress     127.0.0.1:8733
```

All four ports must be distinct and loopback-only. ngrok forwards only to
`8733`; it must not expose the authenticated control API or either OpenCode
server.

Logs are written to `$XDG_STATE_HOME/ocint/daemon.log`. Rotation defaults to
10 MiB with five mode-0600 backups.

## Environment

| Variable | Purpose |
| --- | --- |
| `OCINT_DAEMON_CONFIG` | Explicit TOML path |
| `OCINT_DAEMON_API_TOKEN` | Bearer authentication for the control API |
| `OCINT_DAEMON_GITHUB_TOKEN` | GitHub REST authentication |
| `OCINT_DAEMON_SLACK_BOT_TOKEN` | Coordinator Slack Web API authentication |
| `OCINT_DAEMON_SLACK_SIGNING_SECRET` | Slack Events request HMAC verification |
| `OCINT_NGROK_URL` | Static public HTTPS base URL, without `/slack/events` |
| `PATH` | Executable discovery for managed commands |
| `LANG` or `LC_ALL` | Managed command locale |

Secrets belong in the private mode-0600 `daemon.env`, not TOML. See
[`security.md`](security.md) for credential flow.

The explicit live test additionally reads
`OCINT_E2E_SLACK_ACTOR_USER_TOKEN` from mode-0600 `live-e2e.env`. That variable is
not a daemon setting and is never loaded by systemd.

## Managed Files

```text
bin/ocint/config/opencode.daemon.json -> packaged job policy
bin/ocint/config/opencode.coordinator.json -> packaged coordinator policy
bin/ocint/config/daemon.example.toml  -> generic schema example
bin/ocint/config/live-e2e.env.example -> isolated live actor token example
bin/ocint/docs/daemon.md              -> concise daemon index
bin/ocint/docs/daemon/workflow.md     -> minimal operator workflow
ocint/daemon/lch/setup.py             -> initial discovery + writes
ocint/daemon/lch/doctor.py            -> redacted diagnostics
bin/ocint/config/slack-app-manifest.yaml -> least-privilege public Slack app
bin/ocint/config/slack-e2e-actor-manifest.yaml -> test-user OAuth live E2E actor app
```

Uninstall removes only generated user units. Configuration, credentials, the
shared database and coordinator rows, workspace context, OpenCode data, logs,
mirrors, and worktrees are preserved. Commands report the path, outcome,
modification state, and relevant non-secret policy values for every artifact
they handle.
