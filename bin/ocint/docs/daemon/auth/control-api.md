# Control API Authentication

```text
systemd credential
daemon-api-token
       |
       v
ocint control service <--------- CLI Authorization: Bearer <token>
       ^
       |
       +------------------------- browser bearer or HttpOnly cookie
       |
       +------------------------- systemd authenticated health check

Slack event ingress bypasses this token and verifies Slack signatures instead.
```

## Purpose

The control API token protects job submission, status, session inspection,
follow-ups, cancellation, retry, reload, event streams, and the browser
frontend. OpenCode is not exposed directly to users.

Production loads the token through systemd:

```ini
LoadCredential=daemon-api-token:/etc/ocint/credentials/daemon-api-token
```

The CLI reads `OCINT_DAEMON_API_TOKEN` and sends:

```http
Authorization: Bearer <daemon-api-token>
```

## Browser Authentication

The frontend accepts the same bearer token. Opening the root URL once with a
`token` query parameter sets an `HttpOnly`, `SameSite=Strict` cookie for later
requests:

```text
http://127.0.0.1:8732/?token=<daemon-api-token>
```

Query parameters can appear in browser history and local diagnostics. Prefer a
bearer header when using an API client, and use the query flow only for the
loopback browser bootstrap.

## Health Check

`/health` is authenticated. The systemd unit reads its private credential and
sends a bearer request after startup. A process listening on the port is not
considered ready unless the authenticated health request succeeds.

## Slack Exception

`POST /api/slack/events` does not use the control API token because Slack cannot
know it. That endpoint verifies Slack's timestamp and request signature, then
persists the normalized request before acknowledging it.

All other control routes require the daemon API token.

## Rotation

Replace `daemon-api-token`, restart the control service, and update CLI or
browser clients. Existing browser cookies stop authenticating after rotation.

## Troubleshooting

- `401 Unauthorized`: no bearer token, cookie, or accepted query token was supplied.
- CLI authentication fails: verify `OCINT_DAEMON_API_TOKEN` matches the service credential.
- Browser authentication fails after rotation: reopen the loopback URL with the new token.
- Slack returns `401`: diagnose Slack signing credentials, not the control API token.
- Slack returns `503`: authentication passed, but durable job persistence failed.
