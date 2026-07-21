# Daemon Thread Workflow

`ocint daemon` turns a labelled GitHub issue into either a direct reply or a
pull request. Provision it once from the target repository, then use GitHub
issues and comments to request work or ask repository-specific questions.

The provider-neutral thread/task lifecycle is documented in
[`../spec/daemon-thread-tasks.md`](../spec/daemon-thread-tasks.md).

```text
systemd timer -> poll GitHub for open issues labelled "ocint"
                                      |
                                      v
                  persist issue body as the root message
                                       |
                                       v
                       create a thread task and job
                                      |
                                      v
              OpenCode works in an isolated Git worktree
                                       |
                         +-------------+-------------+
                         |                           |
                    clean worktree              changed worktree
                         |                           |
                         v                           v
                reply directly on issue    validate -> commit -> push
                                                     |
                                                     v
                                            create PR -> reply with URL
                                      |
                    new authorized comments
                                      |
                                      v
             reuse the same session, branch, and any PR
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
At the next timer invocation, ocint reads the issue and its comments and lets
OpenCode inspect the repository. If OpenCode leaves the worktree clean, its
terminal response is posted directly on the issue. If it changes the worktree,
ocint validates and publishes those changes as a pull request, then replies with
the URL. Repository state, rather than a model-authored routing label, determines
which path is used.

Removing the label abandons a queued job and skips its current unresolved task.
A running job may finish; its task stays unresolved until that job is terminal,
then is skipped if the label is still absent. Restoring the label makes a skipped
task's messages pending again and creates a replacement even when no new comment
was added.

```text
Issue addressed: <pull-request-url>

To make further changes, add a comment.
```

## Request Follow-Ups

Add comments to the same open issue. On its next invocation, ocint batches the
new comments in chronological order and continues in the original OpenCode
session and worktree. Each batch can independently produce a direct reply or
changes. Changed follow-ups push to the original branch and update the same open
pull request.

Comments added while a batch is running wait for the next invocation. A closed
or merged pull request is not replaced.

Editing a contribution updates stored text only until an addressed task covers
it, and an edit never schedules work by itself. Add a new comment for follow-up
work. In particular, an edit during a successful active attempt may be missed.

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
