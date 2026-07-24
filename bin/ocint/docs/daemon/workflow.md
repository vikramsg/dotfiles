# Daemon Workflow

## Choose Setup Or Apply

```text
Does daemon.toml exist?
  |
  +-- no  -> run lch setup
  |
  `-- yes
       |
       +-- edited TOML or need regenerated units -> run lch apply
       |
       `-- no configuration change -> run neither
```

Note: `daemon.toml` is usually at `XDG_HOME/.config/ocint/daemon.toml`.

Run `setup` once, from the target repository root, to create initial
configuration and install the systemd units:

```bash
ocint daemon lch setup
ocint daemon doctor
```

Run `apply` after editing `daemon.toml` or when the systemd units must be
regenerated:

```bash
ocint daemon lch apply
ocint daemon lch lifecycle
```

A package reinstall does not modify `daemon.toml` and does not require either
command when the installed executable path is unchanged. Routine timer and job
operation also requires neither command.

## Request Work

Create an issue, describe the required repository change, and apply the `ocint`
label. The next timer invocation performs the work and replies with a pull
request.
The issue title becomes the commit and pull-request summary. The daemon
canonicalizes it as `ocint: <issue title>` and does not duplicate an existing
case-insensitive `ocint:` prefix.

```text
systemd timer -> labelled issue -> OpenCode worktree
                                      |
                                      v
                           validate -> commit -> push
                                      |
                                      v
                              pull request -> issue reply
```

## Inspect Or Attach

```bash
ocint daemon lch list
ocint daemon lch status JOB_ID
ocint daemon lch attach JOB_ID
```

List and status work while the service is inactive. Attach requires that exact
job to have a running OpenCode session.

## Request A Follow-Up

Add an authorized comment to the same open issue. The next task reuses the
existing session, worktree, branch, and open pull request.

For command details and failures, read [operations](operations.md). For setup,
read [configuration](configuration.md).
