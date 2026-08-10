# Daemon Security And Authentication

The daemon separates credentials by consumer. It is an orchestration boundary,
not an operating-system sandbox; validation and OpenCode still execute local
code as the daemon user.

## Credential Boundaries

| Credential | API | OpenCode | Validation | Git | GitHub REST | Slack | LCH |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Daemon API token | yes | no | no | no | no | no | attach metadata |
| Ephemeral OpenCode password | client | server | no | no | no | no | live attach |
| SSH identity file | no | no | no | network only | no | no | no |
| GitHub token | no | no | no | no | yes | no | no |
| Slack bot token | no | no | no | no | no | public-thread replies | hidden install |
| Slack signing secret | no | no | no | no | no | inbound signature verification | provisioned secret |

```text
 daemon.env: API token --------> FastAPI and LCH attach authentication
 daemon.env: GitHub token -----> GitHub HTTP client only
 daemon.env: Slack token ------> Slack HTTP client only
 daemon.env: signing secret ---> Slack Events API verifier only
 auth.json symlink ------------> isolated OpenCode only
 SSH identity + known_hosts ---> network Git only
 ephemeral password -----------> daemon <-> OpenCode child
                                      `----> live attach process
```

The API, GitHub, Slack bot token, and Slack signing secret are persisted in
`$XDG_CONFIG_HOME/ocint/daemon.env`. Setup creates that file as a
regular, user-owned mode-0600 file. It is sensitive, but it is not public and is
never committed to the repository.

`ocint daemon lch slack-token` reads a token from a hidden prompt (or piped
stdin), validates it, and atomically updates only its environment assignment.
It prints workspace and bot identity but never the token. Slack uses signed
Events API callbacks for configured public channels and requests exactly
`channels:history` and `chat:write`. The ingress verifies the timestamp and HMAC
signature over the unmodified body before parsing, rejects stale callbacks, and
commits accepted or ignored events durably before acknowledging them. Request
bodies, message text, signatures, signing secrets, and tokens are not logged.

Private `group` payloads may parse as their typed Slack variant, but they are
always recorded as unsupported and never become coordinator work in Phase 1.
No groups scope or `channels:read` scope is requested.

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

OpenCode receives isolated `HOME` and XDG paths plus its ephemeral server
credentials. It must not receive the daemon API token, GitHub token, Slack token, SSH agent,
or SSH identity.

The interactive attach process receives the user's normal environment plus only
the live OpenCode username and password required by `opencode attach`.

## API Exposure

Every route requires `Authorization: Bearer TOKEN`. Cookies and query-string
tokens are rejected. The default bind is loopback. If the API is exposed beyond
loopback, an independently authenticated and encrypted transport is required.
