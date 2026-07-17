# Control API Authentication

Set `OCINT_DAEMON_API_TOKEN` for the daemon and CLI. Every implemented route,
including `/health`, requires an exact `Authorization: Bearer <token>` header.
Cookies and query-string tokens are not accepted.

The API is limited to health, submit, list, and status operations. Bind it to
loopback unless a separately authenticated transport protects it.
