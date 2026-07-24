# Daemon Configuration

Provisioning discovers repository-specific values and writes private managed
configuration. The default path is `$XDG_CONFIG_HOME/ocint/daemon.toml`, falling
back to `~/.config/ocint/daemon.toml`. `OCINT_DAEMON_CONFIG` overrides it.

The tracked schema example is [`../../config/daemon.example.toml`](../../config/daemon.example.toml).

## Provisioning

Run provisioning from the target Git checkout:

```bash
ocint daemon lch provision
ocint daemon doctor
```

Discovery validates every input before its first write:

```text
 target checkout
   +-- isolated effective Git config --------> one push URL + owner/repository
   +-- gh api --hostname github.com user ----> login
   +-- gh repo view OWNER/REPOSITORY --------> canonical repo + default branch
   +-- gh auth token --hostname github.com --> token presence/value for env only
   +-- effective Git author -----------------> name/email
   +-- safe core.sshCommand + ssh -G --------> executable/key/known-hosts
   `-- XDG OpenCode config/auth -------------> model/provider + auth source
             |
             v
 validate remote equality, credentials, policy, ports, paths, linger, units
             |
             v
 atomically write managed files; auth remains a symlink
```

Provision never starts OAuth or device login. It discovers the GitHub token with
`gh auth token --hostname github.com`, preserves an existing daemon API token,
and regenerates the systemd units.

## Root Settings

| Setting | Meaning |
| --- | --- |
| `database_path` | Independent daemon SQLite database |
| `mirror_root` | Managed bare Git mirrors |
| `worktree_root` | Managed per-job worktrees |
| `repositories` | Allowed repository registry |
| `idle_timeout_seconds` | Unchanged idle grace before shutdown |

Mirror and worktree roots must differ.

## Repository Settings

| Setting | Meaning |
| --- | --- |
| `name` | Stable local repository name |
| `remote_url` | SSH remote; HTTP and local paths are rejected |
| `default_branch` | Base branch for worktrees and pull requests |
| `github_repository` | GitHub `owner/repository` |
| `author_name`, `author_email` | Explicit commit identity |
| `actors` | Optional GitHub login allowlist |
| `checks` | Validation commands run in order |

Repository names are unique. An empty actor set permits any authenticated GitHub
actor. Network Git always uses the configured SSH identity and known-hosts file.
Issue titles must follow the target repository's commit and pull-request title
convention. The daemon canonicalizes them with one case-insensitive `ocint:`
prefix before persistence and publication.

## Scheduler And Lifecycle

| Setting | Default | Meaning |
| --- | ---: | --- |
| `scheduler.capacity` | `1` | Concurrent in-process jobs |
| `scheduler.job_timeout_seconds` | `3600` | Maximum job duration |
| `scheduler.shutdown_timeout_seconds` | `30` | Active-job shutdown grace |
| `scheduler.command_timeout_seconds` | `600` | Git and validation timeout |
| `scheduler.command_output_bytes` | `65536` | Error-output limit |
| `lifecycle.startup_delay_seconds` | `60` | Delay after user-manager startup |
| `lifecycle.inactive_interval_seconds` | `900` | Delay after one invocation exits |

Capacity uses an `asyncio.Semaphore`; there is no scheduler polling loop.

## OpenCode, API, And Logging

The daemon starts exactly the configured OpenCode executable and rejects a
version mismatch before work begins. OpenCode receives isolated XDG directories,
an ephemeral server password, and the packaged unattended permission policy.

The API binds to `127.0.0.1:8732` by default. Keep it on loopback unless an
independent authenticated transport protects it.

Logs are written to `$XDG_STATE_HOME/ocint/daemon.log`. Rotation defaults to
10 MiB with five mode-0600 backups.

## Environment

| Variable | Purpose |
| --- | --- |
| `OCINT_DAEMON_CONFIG` | Explicit TOML path |
| `OCINT_DAEMON_API_TOKEN` | Bearer authentication for the control API |
| `OCINT_DAEMON_GITHUB_TOKEN` | GitHub REST authentication |
| `PATH` | Executable discovery for managed commands |
| `LANG` or `LC_ALL` | Managed command locale |

Secrets belong in the private mode-0600 `daemon.env`, not TOML. See
[`security.md`](security.md) for credential flow.

## Managed Files

```text
bin/ocint/config/opencode.daemon.json -> packaged static policy
bin/ocint/config/daemon.example.toml  -> generic schema example
bin/ocint/docs/daemon.md              -> concise daemon index
bin/ocint/docs/daemon/workflow.md     -> minimal operator workflow
ocint/daemon/lch/provision.py         -> discovery + writes
ocint/daemon/lch/doctor.py            -> redacted diagnostics
```

Uninstall removes only generated user units. Configuration, credentials,
database, logs, mirrors, and worktrees are preserved.
