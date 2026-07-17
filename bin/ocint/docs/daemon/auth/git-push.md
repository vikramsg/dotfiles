# Git Push Authentication

```text
SSH agent socket -> clone/fetch/push
local worktree   -> validation/commit
```

Repositories use SSH remotes. The daemon requires an explicit `SSH_AUTH_SOCK`
and passes it only to managed Git clone, fetch, and push network commands.
Local validation and commit do not receive the socket or GitHub token.

Commit author name and email are required per repository in `daemon.toml`.
Confirm access without changing a repository with `git ls-remote <remote>
refs/heads/main`.

The core settings model permits an empty socket path; PR2 composition validates
that it is non-empty before Git network operations are available.
