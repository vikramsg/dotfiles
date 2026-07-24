# Slack Integration Smoke Test

This smoke test verifies that the external Slack ingress can turn an authorized
thread into a validated repository change. Slack transport remains outside the
ocint daemon package; this test covers the integration boundary, not a Slack
adapter implemented under `ocint.daemon`.

## Signal Path

```text
 Slack channel
      |
      | authorized root message
      v
 external Slack ingress ----> durable thread task
                                   |
                                   v
                           OpenCode worktree
                                   |
                                   v
                      validate -> commit -> publish
                                   |
                                   v
                         Slack thread response
```

The smoke signal is a small documentation change. It is easy to review, still
exercises the complete write path, and satisfies the daemon contract that work
must produce a meaningful repository artifact rather than only a chat reply.

## Preconditions

- The Slack app is installed in the test workspace and can read and reply in the
  selected channel.
- The requesting Slack actor and target repository are allowed by the ingress
  policy.
- The daemon lifecycle, repository credentials, and validation commands pass
  `ocint daemon doctor`.
- The test starts in a new Slack thread so an earlier task cannot cover its root
  message.

Do not include tokens, credentials, private URLs, or customer data in the test
message or the generated document.

## Run The Smoke Test

Post a root message in the selected channel:

```text
Add a Slack integration smoke document. Include an ASCII diagram.
```

If follow-up handling is also under test, reply in the same thread after the
first result is published:

```text
Add a troubleshooting checklist to the smoke document.
```

Follow the job without exposing credentials:

```bash
ocint daemon lch lifecycle
ocint daemon lch list --limit 10
ocint daemon lch status JOB_ID
ocint daemon lch logs --lines 200
```

## Expected State

```text
 root message -> actionable -> task A -> job A -> completed -> response
                                                       |
 follow-up message -> actionable -> task B ------------+
                              reuses session/worktree/branch/PR
```

The smoke test passes when all of these outcomes are visible:

- One authorized root message creates one task and one job.
- The prompt contains the root request and preserves the ASCII-diagram
  requirement.
- Validation succeeds and the resulting change contains a readable ASCII
  diagram.
- Exactly one branch and one pull request represent the thread's work.
- The Slack thread receives a terminal response that identifies the published
  result.
- Reconciliation does not create another job when the same Slack event is seen
  again.
- When follow-up is tested, it reuses the existing work artifacts and updates
  the same pull request.

Record the Slack thread link, job ID, pull-request link, and pass/fail result in
the test record. Never record bearer tokens or daemon environment contents.

## Failure Triage

```text
 no task
   +-- app cannot read channel -> check Slack installation and channel access
   +-- actor rejected          -> check ingress actor policy
   `-- duplicate event         -> locate the existing task by source identity

 task exists, no completion
   +-- queued                   -> inspect lifecycle and scheduler capacity
   +-- failed                   -> inspect job stage and bounded daemon logs
   `-- completed, no reply      -> inspect Slack reply delivery and permissions

 duplicate job or pull request
   `-- stop the smoke test and preserve IDs for idempotency investigation
```

A missing reply is not a pass even when a pull request exists. A duplicate job
or pull request is also a failure because event replay must be idempotent.

## Cleanup

Close the test pull request if it is not intended to merge. Keep the Slack
thread and durable job records long enough to diagnose a failure; the daemon
does not own workspace or history deletion.
