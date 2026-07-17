# OpenCode Server Authentication

```text
                  provisioned shared secret
                         /           \
                        v             v
        systemd credential       systemd credential
          server-password        opencode-password
                 |                     |
                 v                     v
          opencode serve        ocint control service
                 ^                     |
                 |                     | HTTP Basic auth
                 +---------------------+
                    loopback HTTP/SSE

The secret authenticates control-to-OpenCode traffic, not model providers.
```

## Purpose

The OpenCode server password prevents other local callers from using the shared
execution plane. The server remains bound to loopback, and the control service
is the authorization boundary for users and channels.

The same provisioned secret is loaded under service-specific credential names:

```ini
# ocint-opencode.service
LoadCredential=server-password:/etc/ocint/credentials/opencode-password

# ocint-daemon.service
LoadCredential=opencode-password:/etc/ocint/credentials/opencode-password
```

The OpenCode service exports the value as `OPENCODE_SERVER_PASSWORD`. The
control service reads `opencode-password` and sends HTTP Basic authentication
as the configured OpenCode username, which defaults to `opencode`.

## Bootstrap

Generate a unique secret without printing it:

```bash
openssl rand -hex 32 | install -m 600 /dev/stdin \
  /path/to/control-credentials/opencode-password
```

Start OpenCode with the same value and point the daemon at the server URL:

```toml
[opencode]
server_url = "http://127.0.0.1:4096"
username = "opencode"
expected_version = "1.17.20"
```

## Credential Boundary

This password is safe to share between the two dedicated services because it
grants access only to the local OpenCode server. It must not grant GitHub, Git,
SSH, Slack, or model-provider access.

OpenCode may separately require model-provider credentials. Those belong to the
OpenCode execution identity and must not contain publication permissions.

## Rotation

Replace the credential source, restart OpenCode, then restart the control
service with the matching value. The daemon will fail its startup health check
when the values differ.

## Troubleshooting

- `401 Unauthorized`: the username or password differs between services.
- Connection refused: OpenCode is not listening on the configured loopback port.
- Version mismatch: the server is healthy but not the configured OpenCode release.
- Daemon never becomes ready: inspect OpenCode health and authentication first.
