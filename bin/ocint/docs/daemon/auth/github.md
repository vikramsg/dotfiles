# GitHub REST Authentication

```text
bootstrap only                              production

existing gh login                          secret provisioner
      |                                           |
      | gh auth token                             | github-token
      | retrieves; does not create                |
      v                                           v
temporary credential file                 systemd LoadCredential
      |                                           |
      +-------------------+-----------------------+
                          |
                          v
                  ocint control service
                          |
                          | Authorization: Bearer <token>
                          v
                    GitHub REST API
                   /               \
                  v                 v
          issue polling/comments   PR lookup/create

OpenCode and validation subprocesses receive no GitHub token.
```

## Purpose

The GitHub token authenticates control-service requests to the GitHub REST API.
It is used by `GitHubChannel` for issue polling and comments and by
`GitHubPublisher` for pull request lookup and creation.

The token does not authenticate the current SSH Git remote. Clone, fetch, and
push authentication are documented in [Git Push Authentication](git-push.md).

## Bootstrap Credential

Bootstrap acceptance may reuse the operator's existing GitHub CLI login:

```bash
gh auth status
gh auth token
```

`gh auth token` reads the token already stored by `gh auth login`. It does not
mint, create, or rotate a token. The daemon does not execute `gh`; the parent
operator retrieves the existing token and supplies it to the control service.

For the acceptance run, the token was copied into the isolated control
credential directory without printing it:

```bash
gh auth token | install -m 600 /dev/stdin \
  /path/to/control-credentials/github-token
```

This ambient `gh` flow is limited to bootstrap acceptance.

## Production Credential

Production loads a separately provisioned token through systemd:

```ini
LoadCredential=github-token:/etc/ocint/credentials/github-token
```

systemd exposes the credential inside `$CREDENTIALS_DIRECTORY`. The control
service reads `github-token` during composition and keeps it out of OpenCode and
validation command environments.

Prefer a fine-grained token restricted to the configured repositories. Grant
only the permissions required by enabled features:

- Pull requests read/write for PR discovery and creation.
- Issues read/write when GitHub issue ingestion or status comments are enabled.
- Repository metadata read as required by GitHub.

Git push permission is not required on this REST token when the repository
remote uses SSH.

## HTTP Contract

GitHub API clients send:

```http
Authorization: Bearer <github-token>
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2022-11-28
```

PR publication first searches by repository, head branch, and base branch. It
creates a PR only when no matching open PR exists. GitHub issue comments include
a stable hidden delivery marker so retries can find and update prior delivery.

## Rotation

Provision the replacement token at the credential source, restart the control
service, and verify GitHub API access. Revoke the previous token only after the
replacement is active.

Never place the token in daemon TOML, OpenCode configuration, prompts, logs,
command arguments, Git remotes, or validation environments.

## Troubleshooting

- `401 Unauthorized`: the token is missing, malformed, or revoked.
- `403 Forbidden`: repository access or required fine-grained permission is missing.
- `403` with rate-limit headers: wait for reset or review request frequency.
- PR push succeeds but PR creation fails: Git transport auth works, but REST auth does not.
- PR creation succeeds but push fails: REST auth works, but Git transport auth does not.
