# Daemon Pull Request Workflow

```text
systemd timer -> one daemon invocation -> one GitHub poll
                                      |
labelled issue -> authorize -> persist comments/prompt -> permanent job
                                      |
private OpenCode session -> validate -> commit -> explicit SSH push
                                      |
create/reuse owned PR -> marker-protected response -> address batch
                                      |
unchanged idle generation for 60s -> normal two-server shutdown
```

Initial work includes title, body, and chronological authorized comments.
Follow-ups batch new chronological actor-attributed comments, retain the newest
as the durable anchor, and reuse the original session, worktree, branch, and PR.
Each prompt includes GitHub comment IDs, and each successful push advances the
durable Git baseline before publication.
Push state, pull-request stage, and the new baseline form one durable checkpoint.
Comments arriving during an active batch wait for the next invocation. A closed
or merged owned PR errors the batch before execution and is never replaced.

## Prerequisites

Use Linux with a working systemd user manager and user lingering. Install these
commands on `PATH`: Git, GitHub CLI (`gh`), OpenSSH, OpenCode, `uv`, and
`systemctl`/`loginctl`. Before provisioning:

1. Check out the target GitHub repository over SSH and enter its root.
2. Configure an effective Git author name/email and push remote.
3. Configure SSH so `ssh -G github.com` resolves exactly one existing,
   user-owned mode-0600 identity and one readable known-hosts file.
4. Authenticate `gh` to `github.com`. Provision uses only the existing token; it
   never starts OAuth or refreshes authentication.
5. Install OpenCode exactly at version 1.17.20, configure it under XDG config,
   select a `provider/model`, and ensure its
   XDG data auth file exists as a user-owned mode-0600 regular file.
6. Enable lingering outside ocint if needed:

   ```bash
   loginctl enable-linger "$USER"
   ```

The Git push remote must identify the same `owner/repository` selected by
`gh repo view`. HTTPS, local, mismatched, detached, and ambiguous SSH setups are
rejected before any managed file is written.

## Install From The Checkout

An ordinary tool install includes the policy resource; no post-install copy is
needed:

```bash
uv tool install ./bin/ocint
ocint daemon --help
ocint daemon doctor --help
```

When updating the tool, reinstall it before provisioning. Re-enabling an
already elapsed timer can trigger its service immediately, so finish credential
and port checks first.

## What Provision Discovers

From the target checkout root, provision runs the equivalent of:

```text
effective Git push remote                        -> OWNER/REPOSITORY
gh api --hostname github.com user                -> actor/agent login
gh repo view OWNER/REPOSITORY --json nameWithOwner,defaultBranchRef
gh auth token --hostname github.com             -> token (never printed)
git effective branch/author config
safe core.sshCommand + ssh -G [-p port] [-l user] <remote-host>
$XDG_CONFIG_HOME/opencode/opencode.json          -> model/provider
$XDG_DATA_HOME/opencode/auth.json                -> symlink source
```

The command environment closes stdin, applies a 30-second bound, disables
prompts and pagers, strips `GH_REPO`, `GH_HOST`, and Git config override
variables, and rejects ambient `GIT_SSH_COMMAND`/`GIT_SSH`. Git discovery occurs
before any GitHub query, and multiple push URLs are rejected.

It validates the packaged static policy and requires OpenCode exactly 1.17.20,
then validates the other installed binaries,
remote equality, SSH files, auth file, destination safety, linger, and ports
4097/8732. Only then does it create private managed directories, atomically
write `daemon.env`, `daemon.toml`, and the effective OpenCode config, create the
auth symlink, and install the two user units.

```bash
ocint daemon lch provision
ocint daemon doctor
ocint daemon doctor --json
```

Doctor prints the effective nonsecret TOML, required environment variable names
and presence, packaged/effective policy, OpenCode executable/version/model and
paths, live `gh` identity/repository/token presence, Git/SSH values, storage and
migration state, exact units, timer state/schedule/linger, and ports. It renders
the complete report before returning nonzero for required failures. It never
prints tokens, auth contents, key contents, or secret provider options.

## Timer Timing

```text
user manager starts
      |
      | 1 minute (OnStartupSec=1m)
      v
service invocation -> work + 60s idle -> inactive
                                      |
                                      | 15 minutes
                                      | (OnUnitInactiveSec=15m)
                                      v
                               next invocation
```

`OnStartupSec` is relative to the user manager, which lingering starts at boot.
It is not relative to login. `enable --now` during install/reinstall can make an
overdue timer fire immediately.

## Create Initial Work

1. In GitHub, create the configured `ocint` label if repository policy has not
   already created it. Provision does not create labels.
2. Open an issue authored by an allowed actor.
3. Put the complete initial request in its title/body.
4. Add any pre-execution clarifications as comments by allowed actors.
5. Apply the `ocint` label.

At the next timer invocation, ocint lists open labelled issues once. It excludes
pull requests from the issues endpoint, authorizes the issue author and every
comment independently, persists unseen comments, and creates one permanent job.
The first prompt contains the title, body, and all authorized human comments in
creation-time/ID order with actor attribution.

After execution and validation, ocint commits with the discovered author,
pushes `ocint/<job-id>` using the explicit SSH files, and creates the initial PR.
Its title is exactly the persisted issue title byte-for-byte. It then posts:

```text
Issue addressed: <pull-request-url>

To make further changes, add a comment.
```

The hidden marker makes response recovery idempotent if GitHub accepted a POST
before local persistence completed.

## Timer-Only Verification

Do not run `ocint daemon run` for normal acceptance. Verify the installed timer
and allow it to trigger naturally:

```bash
ocint daemon lch status
systemctl --user list-timers ocint-daemon.timer
ocint daemon lch logs --lines 200
ocint daemon doctor
```

Confirm the issue response, exact PR title, expected branch changes, and that
both 4097 and 8732 close after the unchanged 60-second idle grace. The service
should become inactive; the timer remains active.

## Follow-Ups And Recovery

Add one or more new authorized human comments to the same open issue. The next
poll batches them chronologically. The newest is the active anchor and earlier
ones become `batched`. Ocint persists the immutable prompt before scheduling,
then reuses the same job, OpenCode session, worktree, branch, and PR. A comment
arriving while a batch is active waits for a later batch.

On restart, the job prompt and active anchor recover the batch. Stage
checkpoints skip already completed execution, validation, commit, or push work.
Marker lookup recovers an already-posted response rather than duplicating it.

If the owned PR is closed or merged, follow-up comments become `errored`, ocint
posts one marker-protected explanation, and no replacement PR is created.
Unauthorized comments become `rejected` and receive one idempotent explanation;
they do not block authorized comments.

## Logs And Troubleshooting

```bash
ocint daemon lch logs --lines 200
ocint daemon lch logs --follow
```

- **OAuth/device prompt:** stop; provision is allowed to use only
  `gh auth token --hostname github.com`. Authenticate `gh` separately.
- **4096 occupied:** expected for an interactive OpenCode server. The daemon
  uses private 4097. A conflict on 4097 or API 8732 must be resolved.
- **OpenCode DB lock:** verify isolated XDG data/config paths and the auth
  symlink. The daemon must not share the interactive OpenCode database.
- **Startup appears stuck:** OpenCode health has a 120-second startup timeout;
  inspect journald and doctor version/path results.
- **Journald permission error:** run as the user owning the user manager and
  verify user-journal access. Do not convert this to a system service.
- **SSH ambiguity:** remove extra effective identities/known-host files or make
  Git's safe `core.sshCommand` select exactly one of each.

## Uninstall And Full Cleanup

```bash
ocint daemon lch uninstall
```

Uninstall stops/disables the timer, stops the service, removes only its two unit
files, and reloads systemd. It preserves all managed configuration, credentials,
the auth symlink, database, mirrors, and worktrees.

For a full manual cleanup, first inspect and preserve
`$XDG_STATE_HOME/ocint/daemon.sqlite` (or its configured equivalent). Never
delete the database as part of routine cleanup. After the units are uninstalled,
the operator may separately remove the non-database environment/config files,
auth symlink, mirrors, and worktrees and may uninstall the uv tool. Disabling
linger is a host policy decision and is not performed by ocint.
