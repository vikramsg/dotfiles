# Daemon Pull Request Workflow

`ocint daemon` turns a labelled GitHub issue into a pull request. Provision it
once from the target repository, then use GitHub issues and comments to request
work.

The provider-neutral thread/task lifecycle is documented in
[`../spec/daemon-thread-tasks.md`](../spec/daemon-thread-tasks.md).

```text
systemd timer -> poll GitHub for open issues labelled "ocint"
                                      |
                                      v
                     create a permanent daemon job
                                      |
                                      v
               OpenCode edits an isolated Git worktree
                                      |
                                      v
                    validate -> commit -> push
                                      |
                                      v
                    create PR -> reply on issue
                                      |
                    new authorized comments
                                      |
                                      v
              reuse the same session, branch, and PR
```

## Install And Provision

The target repository must be checked out over SSH. Git author settings, SSH,
`gh`, and OpenCode must already be configured. The host also needs a systemd
user manager. If user lingering is disabled, enable it first:

```bash
loginctl enable-linger "$USER"
```

Then install and provision ocint:

```bash
uv tool install ./bin/ocint
ocint daemon lch provision
ocint daemon doctor
```

Run these commands from the target repository root. Provision discovers that
repository and installs the systemd user service and timer. If `doctor` reports
a failure, correct it before creating work.

## Request Work

1. Create the `ocint` label in the repository if it does not exist.
2. Open an issue with the complete request in its title and body.
3. Add any clarifications as comments.
4. Apply the `ocint` label.

The issue author and commenters must be allowed by the provisioned actor policy.
At the next timer invocation, ocint reads the issue and its comments, performs
the work, opens a pull request, and replies with its URL.

```text
Issue addressed: <pull-request-url>

To make further changes, add a comment.
```

## Request Follow-Ups

Add comments to the same open issue. On its next invocation, ocint batches the
new comments in chronological order and continues in the original OpenCode
session and worktree. It pushes to the original branch and updates the same open
pull request.

Comments added while a batch is running wait for the next invocation. A closed
or merged pull request is not replaced.

## Check Progress

Let the installed timer run the daemon during normal use. Inspect it with:

```bash
ocint daemon lch status
systemctl --user list-timers ocint-daemon.timer
ocint daemon lch logs --lines 200
ocint daemon lch logs --follow
ocint daemon doctor
```

The service becomes inactive after work completes and the daemon remains idle
for 60 seconds. The timer stays active and starts the next invocation later.

## Uninstall

```bash
ocint daemon lch uninstall
```

Uninstall removes the systemd user units but preserves daemon configuration,
credentials, database, mirrors, and worktrees. See [`daemon.md`](../daemon.md)
for architecture, configuration, recovery, cleanup, and troubleshooting details.
