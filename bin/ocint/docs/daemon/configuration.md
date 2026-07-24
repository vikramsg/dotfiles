# Daemon Configuration

Initial setup discovers repository-specific values and writes private managed
configuration. The default path is `$XDG_CONFIG_HOME/ocint/daemon.toml`, falling
back to `~/.config/ocint/daemon.toml`. `OCINT_DAEMON_CONFIG` overrides it.

The tracked schema example is [`../../config/daemon.example.toml`](../../config/daemon.example.toml).

## Setup And Ownership

Run initial setup from the target Git checkout:

```bash
ocint daemon lch setup
ocint daemon doctor
```

`daemon.toml` becomes user-owned after its first creation. Command behavior is
deliberately asymmetric:

```text
daemon.toml absent  -> setup discovers values and creates it
daemon.toml exists  -> setup reuses it byte-for-byte
apply               -> reads it and regenerates systemd units only
package reinstall   -> does not read or modify it
uninstall           -> preserves it and all daemon state
```

Defaults apply only when `setup` first creates the file. Changing a default in
Python does not migrate an explicit value already stored in `daemon.toml`. Edit
the TOML and run the following command to apply lifecycle changes:

```bash
ocint daemon lch apply
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

Setup never starts OAuth or device login. It discovers the GitHub token with
`gh auth token --hostname github.com`, preserves an existing daemon API token,
and installs the systemd units. A later setup reuses the existing TOML without
running discovery again.

## Optional Private Slack Source

Slack polling is enabled only when `[slack]` is present. Every configured
channel is a private channel mapped to one configured repository:

```toml
[slack]
workspace_id = "T01234567"
completion_reaction = "white_check_mark"

[[slack.channels]]
channel_id = "C01234567"
repository = "repository"
authorized_users = ["U01234567"]
initial_oldest = "1753380000.123456"
```

`authorized_users` contains Slack member IDs, not display names. Channel IDs
must be unique. `initial_oldest` is an inclusive first-run boundary; set it to
the timestamp of the prepared first root so older channel history cannot become
work. Only configured channels are polled.

Create the Slack app from
[`../../config/slack-app-manifest.yaml`](../../config/slack-app-manifest.yaml).
It requests exactly `groups:history`, `chat:write`, and `reactions:write`.
Socket Mode, Events API subscriptions, slash commands, and public-channel
history are not used.

Install or rotate the bot token without putting it in argv:

```bash
ocint daemon lch slack-token
# automation:
printf '%s\n' "$SLACK_TOKEN" | ocint daemon lch slack-token
```

The hidden prompt validates `auth.test`, required scopes, and the configured
workspace before atomically updating `daemon.env`.

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
| `lifecycle.inactive_interval_seconds` | `600` | Delay after one invocation exits |

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
| `OCINT_DAEMON_SLACK_BOT_TOKEN` | Optional private-channel Slack bot authentication |
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
ocint/daemon/lch/setup.py             -> initial discovery + writes
ocint/daemon/lch/doctor.py            -> redacted diagnostics
bin/ocint/config/slack-app-manifest.yaml -> least-privilege private Slack app
```

Uninstall removes only generated user units. Configuration, credentials,
database, logs, mirrors, and worktrees are preserved. Commands report the path,
outcome, modification state, and relevant non-secret policy values for every
artifact they handle.
