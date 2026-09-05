# Daemon Security And Authentication

The daemon limits credentials and capabilities at process boundaries. It is an
orchestration boundary, not an operating-system sandbox: all local processes
still run as the daemon user.

## Credential Boundaries

| Credential | Job OpenCode | Coordinator OpenCode | Git/GitHub | Slack adapter | Ingress | ngrok |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Daemon API token | no | no | no | no | no | no |
| Ephemeral OpenCode password | server only | server only | no | no | no | no |
| SSH identity | no | no | network Git only | no | no | no |
| GitHub token | no | no | GitHub REST only | no | no | no |
| Slack bot token | no | no | no | Web API replies/lookups | no | no |
| Slack signing secret | no | no | no | no | HMAC verification | no |
| ngrok authtoken | no | no | no | no | no | ngrok config only |

```text
 daemon.env: API token ------------> control API + LCH attachment
 daemon.env: GitHub token ---------> GitHub HTTP adapter
 daemon.env: Slack bot token ------> Slack Web API adapter
 daemon.env: Slack signing secret -> POST /slack/events verifier
 daemon.env: static ngrok URL -----> unit generation (public hostname)
 auth.json symlinks --------------> isolated OpenCode data homes
 SSH identity + known_hosts ------> network Git only
 ngrok.yml authtoken -------------> ngrok process only
```

The API, GitHub, Slack, signing-secret, and static-URL values are persisted in
`$XDG_CONFIG_HOME/ocint/daemon.env`. Setup creates that file as a
regular, user-owned mode-0600 file. It is sensitive, but it is not public and is
never committed to the repository.

The interactive `$XDG_CONFIG_HOME/opencode/opencode.json` is a non-secret source
for model and provider selection. It may be a user-owned regular file or a
user-owned symlink whose fully resolved target is a user-owned regular file.
The target must not be writable by group or others; modes 0600, 0640, and 0644
are valid. LCH reads the validated target as one stable snapshot, then projects
only the selected provider and model into separate restricted, user-owned
mode-0600 job and coordinator configs. Provider authentication remains in the
separate mode-0600 `auth.json`; neither the source-config exception nor its
symlink support weakens credential or generated-config checks.

The **ocint E2E actor** User OAuth Token is the sole assignment in
`$XDG_CONFIG_HOME/ocint/live-e2e.env`, also a regular mode-0600 file. Only the
explicit live pytest sources it. Daemon and ngrok systemd units do not load that
file, setup and doctor do not require it, and the harness never prints it. The
app grants user OAuth `chat:write`; its retained bot `chat:write` scope and bot
identity are unused by E2E. It has no event subscription, Socket Mode, or
interactivity. The authorized test user must belong to the public test channel.
The harness passes this token only to its actor `SlackClient`. Its systemctl,
ngrok, OpenCode, and LCH subprocess environments use the centralized scrub
policy and never inherit the actor token.

```text
live-e2e.env: test user xoxp token -> explicit harness -> one marked root
daemon.env: production bot token -> Slack adapter      -> replies + lookups
```

`ocint daemon lch slack-token` reads a token from a hidden prompt (or piped
stdin), validates it, and atomically updates only its environment assignment.
It prints workspace and bot identity but never the token. Slack uses the Events
API `message.channels` event for public-channel input and the Web API for thread
reply delivery. The app needs exactly `channels:history` and `chat:write`; there
is no Socket Mode, reaction, file-upload, or private-channel scope.

The ngrok service does not load `daemon.env`. Its generated command contains
the public static URL and an isolated environment with only HOME,
`XDG_CONFIG_HOME`, and locale. Its account credential remains in private ngrok
configuration.

Coordinator OpenCode runs without `--print-logs`, with stdin, stdout, and stderr
connected to `/dev/null`. Prompts, responses, and provider diagnostics therefore
cannot flow into coordinator stdout/stderr or the systemd journal. Health and
exit status remain observable through the private HTTP adapter and safe daemon
logs.

## Signed, Durable Ingress

The public surface is one route:

```text
Slack -> static ngrok HTTPS URL -> 127.0.0.1:8733 -> POST /slack/events
```

The handler enforces a byte limit while streaming, requires Slack's timestamp
and `v0` signature, rejects requests outside the default five-minute window,
and compares HMAC-SHA256 over the exact raw body in constant time. It parses
only after authentication and requires the configured workspace.

For a valid event, one transaction records the provider event, normalized
message, conversation, and newly eligible turns before returning `200`. A
database failure returns 5xx so Slack retries. Duplicate identities acknowledge
without another turn; conflicting identities and unsupported or unauthorized
events are durably classified without running OpenCode. The request handler
never waits for OpenCode and never posts a Slack reply.

Production authorization accepts only configured human member IDs in configured
public channels. Bot-authored messages, including this bot's own replies, are
ignored. Edits, deletions, file-only messages, empty messages, unsupported
subtypes, unconfigured channels, and unauthorized actors do not become turns.

The live harness does not weaken that policy. It authenticates an `xoxp` User
OAuth Token in the configured workspace and requires that user ID in the target
channel's `authorized_users`. Slack marks the resulting `message.channels`
callback with that authorized user plus the actor app's `bot_id`, `app_id`, and
exact `client_msg_id`. A test-only classifier accepts only that prearmed public
root and its exact retries. Production classification is unchanged: all
bot/app-authored events, including production replies, remain ignored.

The parser also has a typed private `channel_type="group"` variant so provider
payloads remain explicit. Private deployment is not implemented: the manifest,
doctor, access validation, and examples never request `message.groups` or
`groups:history`.

## Live Attachment Authentication

The OpenCode server password is generated with cryptographic randomness for each
daemon invocation. It is never written to `daemon.env`, TOML, SQLite, logs, or
the command line.

```text
 private daemon.env                 daemon memory
 +----------------------+           +--------------------------+
 | daemon API token     |--Bearer-->| attach metadata endpoint |
 +----------------------+           | OpenCode user + password |
                                    +------------+-------------+
                                                 |
                                                 | loopback response
                                                 v
                                    +--------------------------+
                                    | lch attach process       |
                                    | OPENCODE_SERVER_USERNAME |
                                    | OPENCODE_SERVER_PASSWORD |
                                    +------------+-------------+
                                                 |
                                                 v
                                       private OpenCode server
```

The sequence is:

1. LCH validates and reads the provisioned API token.
2. LCH calls `GET /api/jobs/JOB_ID/attach` over the configured local API.
3. Bearer authentication is checked with constant-time comparison.
4. The daemon verifies that the job is running and belongs to its current
   OpenCode server.
5. The response carries URL, directory, session, username, and the ephemeral
   password.
6. LCH puts username and password in the child process environment and launches
   the configured OpenCode executable.

Credentials are not included in argv, where process listings would expose them.
The attach endpoint is unavailable when the daemon is inactive, and stale or
terminal jobs receive a conflict response.

## Process Environments

Validation receives only `PATH`, `LANG`, and `CI=1`. Local Git additionally
receives `GIT_TERMINAL_PROMPT=0`. Network Git receives a constrained
`GIT_SSH_COMMAND` with batch mode, one identity, one known-hosts file, and strict
host checking.

Both OpenCode children receive isolated `HOME` and XDG paths plus ephemeral
server credentials, provider authentication, PATH, and locale. They do not
receive the daemon API token, GitHub token, Slack token, signing secret, ngrok
URL, SSH agent, or SSH identity.

The coordinator OpenCode policy disables sharing, plugins, MCP, LSP, formatter,
shell, edits, writes, patches, external-directory access, and the interactive
question tool. It allows read/list/glob/grep inside the generated context
workspace plus web search/fetch. That workspace contains only `AGENTS.md` and a
safe repository catalogue, not target checkouts or credentials.

The interactive attach process receives the user's normal environment plus only
the live OpenCode username and password required by `opencode attach`.

## API Exposure

Every control API route requires `Authorization: Bearer TOKEN`. Cookies and
query-string tokens are rejected. Configuration requires a loopback bind; keep
the control API private.

The Slack ingress has no control, attachment, documentation, proxy, or OpenCode
routes. Keep `8732`, `8733`, `4097`, `4098`, and ngrok's local inspection port
closed to inbound network traffic. The managed tunnel targets only `8733` and
disables ngrok inspection.

## Phase 1 Limitations

The word “sandbox” describes OpenCode permissions and workspace configuration,
not kernel or container isolation. Web research can still receive text chosen
by the model. Phase 1 has one coordinator worker, one generated context
workspace, and no delegation to repository OpenCode servers. It cannot inspect
or change target repositories, execute checks, create tasks or jobs, use Git,
or publish to GitHub. Only coordinator output is sent to Slack.
