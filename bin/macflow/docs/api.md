# Macflow APIs

Macflow exposes one HTTP API over its loopback server:

- [HTTP reference](http-api.md): authentication, routes, and payloads used by the
  CLI and other external processes. This includes `POST /v1/ui`, which renders a
  native surface from an A2UI payload.

The `macflow` CLI is a client for these routes; it does not control macOS
directly.
