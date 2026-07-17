# OpenCode Server Authentication

Set the same generated secret as `OPENCODE_SERVER_PASSWORD` on OpenCode and
`OCINT_DAEMON_OPENCODE_PASSWORD` on the daemon. The daemon uses HTTP Basic auth
with the configured username, verifies `/global/health`, and refuses any
version other than 1.17.20.

Keep OpenCode on loopback and do not expose SSH, GitHub, or daemon API
credentials to its process.
