# Control API Authentication

```text
client -- bearer token --> loopback control API
```

Set `OCINT_DAEMON_API_TOKEN` for the daemon and CLI. Every implemented route,
including `/health`, requires an exact `Authorization: Bearer <token>` header.
Cookies and query-string tokens are not accepted.

The API is limited to health, submit, list, and status operations. Bind it to
loopback unless a separately authenticated transport protects it.

The core settings model permits an empty token; PR2 composition validates that
the token is non-empty before the control API starts.
