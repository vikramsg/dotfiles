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
configuration, provision both OpenCode policies, generate coordinator context,
and install all four systemd units:

```bash
export OCINT_NGROK_URL=https://YOUR_STATIC_NGROK_DOMAIN
ocint daemon lch setup
ocint daemon migrate
ocint daemon doctor
```

Run `apply` after editing `daemon.toml` or when the systemd units must be
regenerated:

```bash
ocint daemon lch apply
ocint daemon doctor
ocint daemon lch lifecycle
```

A package reinstall does not modify `daemon.toml` and does not require either
command when the installed executable path is unchanged. Initial `setup`
enables the GitHub timer but leaves coordinator and ngrok disabled. Subsequent
`setup` and `apply` preserve and report their actual enablement; explicitly
disable both units before a live-test window rather than relying on apply.

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

Slack has a different Phase 1 workflow. Post a normal root message in a
configured public channel as an authorized human. The signed Events API
callback is committed before acknowledgment; the always-on coordinator answers
in the same root thread. Authorized replies continue the same OpenCode session.

```text
Slack root -> signed event -> durable conversation -> coordinator OpenCode
                                                          |
                                                          v
                                                  Slack thread reply
```

The coordinator can answer questions, use web research, and identify a likely
repository from its safe catalogue. It cannot inspect or modify that repository
or start the GitHub job workflow. When repository work is needed, it names the
likely repository and objective and says execution is not available yet.

Retryable OpenCode recovery is ordered but bounded. The configured retry count
is the number of retries after the initial attempt; after that budget is
exhausted, the coordinator delivers its safe failure response and allows the
next message in the thread to run. Slack delivery keeps retrying independently
until the already persisted response is delivered.

## Inspect Or Attach

```bash
ocint daemon lch list
ocint daemon lch status JOB_ID
ocint daemon lch attach JOB_ID
```

List and status work while the service is inactive. Attach requires that exact
job to have a running OpenCode session.

## Request A Follow-Up

Add an authorized GitHub comment to reuse the job session, worktree, branch,
and open pull request. Add an authorized Slack thread reply to reuse only that
coordinator conversation and coordinator OpenCode session; it does not reuse or
create repository execution state.

## Roll Out The Coordinator

After setup/apply and a healthy doctor report, explicitly keep the production
coordinator units disabled while running the explicit live E2E described in
[operations](operations.md). Once its probe-scoped database and Slack evidence
passes, start the coordinator before its tunnel:

```bash
systemctl --user enable --now ocint-coordinator.service
systemctl --user enable --now ocint-coordinator-ngrok.service
ocint daemon lch lifecycle
```

For command details and failures, read [operations](operations.md). For setup,
read [configuration](configuration.md).
