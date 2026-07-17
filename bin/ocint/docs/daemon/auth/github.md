# GitHub REST Authentication

Set `OCINT_DAEMON_GITHUB_TOKEN` to a fine-grained token with pull-request
read/write access to configured repositories. The GitHub adapter uses it only
to find an open PR by owner/head/base and create one when absent. It is never
passed to Git, validation, or OpenCode.

SSH credentials, not this REST token, authenticate clone, fetch, and push.
