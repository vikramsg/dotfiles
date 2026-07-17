# GitHub REST Authentication

```text
daemon -- fine-grained token --> GitHub pull-request API
```

Set `OCINT_DAEMON_GITHUB_TOKEN` to a fine-grained token with pull-request
read/write access to configured repositories. The GitHub adapter uses it only
to find an open PR by owner/head/base and create one when absent. It is never
passed to Git, validation, or OpenCode.

SSH credentials, not this REST token, authenticate clone, fetch, and push.

The core settings model permits an empty token; PR2 composition validates that
the token is non-empty before the GitHub adapter starts.
