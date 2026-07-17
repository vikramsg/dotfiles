# Git Push Authentication

Repositories use SSH remotes. The daemon requires an explicit `SSH_AUTH_SOCK`
and passes it only to managed Git clone, fetch, commit, and push commands.
Validation and OpenCode do not receive the socket or GitHub token.

Commit author name and email are required per repository in `daemon.toml`.
Confirm access without changing a repository with `git ls-remote <remote>
refs/heads/main`.
