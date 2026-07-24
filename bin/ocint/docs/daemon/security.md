# Daemon Security And Authentication

The daemon separates credentials by consumer. It is an orchestration boundary,
not an operating-system sandbox; validation and OpenCode still execute local
code as the daemon user.

## Credential Boundaries

| Credential | API | OpenCode | Validation | Git | GitHub REST | LCH attach |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Daemon API token | yes | no | no | no | no | authenticates metadata request |
| Ephemeral OpenCode password | client | server | no | no | no | live process environment |
| SSH identity file | no | no | no | network only | no | no |
| GitHub token | no | no | no | no | yes | no |

```text
 daemon.env: API token --------> FastAPI and LCH attach authentication
 daemon.env: GitHub token -----> GitHub HTTP client only
 auth.json symlink ------------> isolated OpenCode only
 SSH identity + known_hosts ---> network Git only
 ephemeral password -----------> daemon <-> OpenCode child
                                      `----> live attach process
```

The API and GitHub tokens are persisted in
`$XDG_CONFIG_HOME/ocint/daemon.env`. Setup creates that file as a
regular, user-owned mode-0600 file. It is sensitive, but it is not public and is
never committed to the repository.

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
credentials. It must not receive the daemon API token, GitHub token, SSH agent,
or SSH identity.

The interactive attach process receives the user's normal environment plus only
the live OpenCode username and password required by `opencode attach`.

## API Exposure

Every route requires `Authorization: Bearer TOKEN`. Cookies and query-string
tokens are rejected. The default bind is loopback. If the API is exposed beyond
loopback, an independently authenticated and encrypted transport is required.
