# Git Push Authentication

```text
SSH remote                                  HTTPS remote

control-only SSH agent                     systemd credentials
        |                                  /                 \
        | SSH_AUTH_SOCK                   v                   v
        |                         git-config          git-push-credential
        |                                  \                 /
        |                                   v               v
        +--------------------------> control publication environment
                                             |
                                             | git clone/fetch/push
                                             v
                                      configured Git remote

OpenCode and validation subprocesses receive neither credential path.
```

## Purpose

Git transport credentials authenticate managed mirror fetches and branch
pushes. They are separate from the GitHub REST token used to create pull
requests.

The repository configuration selects the transport through `remote_url`:

```toml
remote_url = "git@github.com:vikramsg/dotfiles.git"
```

## SSH Transport

For an SSH remote, the control process receives an explicit `SSH_AUTH_SOCK`.
The repository manager passes it only to Git publication commands:

```bash
git push --no-verify --set-upstream origin ocint/<job-id>
```

The agent must contain a key authorized for the configured repository. OpenCode
must not inherit `SSH_AUTH_SOCK`.

Validate SSH access without changing the repository:

```bash
git ls-remote git@github.com:vikramsg/dotfiles.git refs/heads/main
```

## HTTPS Transport

For an HTTPS remote, systemd loads the tracked Git credential configuration and
a secret credential payload:

```ini
LoadCredential=git-config:/etc/ocint/git-publisher.config
LoadCredential=git-push-credential:/etc/ocint/credentials/git-push-credential
```

The control service sets `GIT_CONFIG_GLOBAL` and
`OCINT_GIT_PUSH_CREDENTIAL` only in the Git publication environment. The
configured credential helper reads the payload when Git requests credentials.

The credential payload must use the format expected by Git's credential
protocol, for example:

```text
protocol=https
host=github.com
username=x-access-token
password=<secret>
```

Store it with mode `0600` and never commit it.

## Isolation

Validation commands receive only their explicit execution environment. They do
not receive publication `HOME`, `GIT_CONFIG_GLOBAL`,
`OCINT_GIT_PUSH_CREDENTIAL`, or `SSH_AUTH_SOCK`.

The OpenCode systemd service runs under a separate OS identity and does not load
Git publication credentials.

## Troubleshooting

- `Permission denied (publickey)`: the SSH agent is absent or lacks an authorized key.
- `terminal prompts disabled`: Git could not obtain a non-interactive HTTPS credential.
- Clone succeeds but push fails: the credential has read access but lacks write access.
- REST PR calls succeed but Git fails: diagnose this transport path, not `github-token`.
