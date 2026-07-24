# Daemon Operations

`ocint daemon lch` is the operator surface for a daemon installed through the
Linux user-systemd lifecycle.

## Commands

```text
provision        discover configuration and install the timer
install          regenerate and enable existing user units
lifecycle        show timer, service, schedule, and log state
list             list durable jobs from SQLite
status JOB_ID    show one durable job
attach JOB_ID    attach to that job's live OpenCode session
logs             read or follow private rotating logs
uninstall        remove only the generated user units
```

`list` and `status` read the daemon database directly, so they work while the
bounded service is inactive and do not require API credentials.

```text
 daemon.sqlite
      |
      +--> lch list
      `--> lch status JOB_ID
```

## Inspect Jobs

```bash
ocint daemon lch list
ocint daemon lch status JOB_ID
```

The list keeps full IDs copyable at normal terminal widths. Detailed status
includes state, stage, repository, actor, session, worktree, branch, commit,
pull request, and error.

## Attach

```bash
ocint daemon lch attach JOB_ID
```

Attachment requires a currently running job with a provisioned OpenCode session.
The command behaves like `opencode attach`: it inherits the terminal and remains
interactive until OpenCode exits. LCH fixes the URL, directory, and session from
the durable job, so it intentionally accepts no OpenCode options.

```text
lch attach JOB_ID
      |
      +--> read API token from private daemon.env
      +--> request live attachment metadata over loopback
      +--> receive ephemeral OpenCode credentials in memory
      `--> opencode attach URL --dir WORKTREE --session SESSION
```

See [`security.md`](security.md) for the authentication boundary.

## Lifecycle And Logs

```bash
ocint daemon lch lifecycle
ocint daemon lch logs --lines 200
ocint daemon lch logs --follow
```

The lifecycle view reports installation, timer schedule, service result, and log
path. Logs are read directly rather than through journald and continue across
rotation.

## Failure Handling

- Invalid actors and repositories fail before persistence.
- Job timeout records `job timed out`.
- Validation failure prevents commit and push.
- Git failure prevents publication.
- GitHub failure leaves the durable stage available for inspection.
- A closed or merged owned pull request is reported and never replaced.
- Attach returns a conflict when the job has no live session.

Subprocess output is bounded by `command_output_bytes`. Timed-out managed
commands are terminated as process groups.

## Troubleshooting

### Service is not running

The service is normally inactive between timer invocations. Check the timer and
last result:

```bash
ocint daemon lch lifecycle
ocint daemon lch logs --lines 200
ocint daemon doctor
```

### Job remains queued

Inspect the lifecycle and logs. Queued jobs are scheduled at startup; rows
inserted externally after startup are intentionally not polled.

### Job failed validation

Use `lch status JOB_ID`, then run the configured check from the retained
worktree. Validation failures do not commit or push.

### Attach fails

Confirm the job is `running`, has a session and worktree, and the service is
active. Completed, failed, queued, and stale sessions are not attachable.

### Git authentication fails

Run `ocint daemon doctor`. Network Git uses one explicit mode-0600 identity,
strict host checking, and no SSH-agent fallback.

### OpenCode reports a lock

Confirm the service uses its isolated `xdg_data_home` and that managed
`auth.json` is a symlink. It must not share the interactive OpenCode database.

### Logs cannot be read

Use `lch lifecycle` to confirm the path. The directory must be user-owned mode
0700, and active and rotated files must be regular user-owned mode-0600 files.
