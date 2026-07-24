# ocint Daemon LCH Diagnostics

This reference provides commands for the workflow in `SKILL.md`. Replace values
in angle brackets and quote paths. Keep secrets out of command output and final
reports.

## Preflight

```bash
git status --short --branch
git log --oneline --decorate -5
command -v ocint
uv tool list
gh auth status
gh repo view --json nameWithOwner,defaultBranchRef
ocint daemon config --path
ocint daemon doctor --json
ocint daemon lch status
systemctl --user status ocint-daemon.timer --no-pager
systemctl --user status ocint-daemon.service --no-pager
systemctl --user list-timers ocint-daemon.timer --no-pager
```

Derive paths from effective configuration rather than assuming defaults:

```bash
DAEMON_DB=$(ocint daemon config | jq -r '.effective.database_path')
OPENCODE_CONFIG=$(ocint daemon config | jq -r '.effective.opencode.config_file')
OPENCODE_DATA=$(ocint daemon config | jq -r '.effective.opencode.xdg_data_home')
OPENCODE_DB="$OPENCODE_DATA/opencode/opencode.db"
OPENCODE_LOG="$OPENCODE_DATA/opencode/log/opencode.log"
```

Do not read `daemon.env` or `auth.json` during normal diagnosis. Doctor reports
whether required credentials and auth links are present without exposing them.

## Optional Reinstall And Provision

Use this only when installation itself is in scope. Stop the service and timer
before removing the executable, but preserve all state files.

```bash
systemctl --user stop ocint-daemon.timer ocint-daemon.service
uv tool uninstall ocint
just --justfile bin/ocint/justfile install
ocint daemon lch provision
ocint daemon lch status
systemctl --user list-timers ocint-daemon.timer --no-pager
```

`provision` installs and enables the timer. Database migration occurs on daemon
startup, so a pre-start doctor can report the previous migration. Do not run a
manual migration to make doctor green. Wait for the timer-triggered daemon cycle,
then check migration state again.

## Create And Trigger An Issue

Get approval for the issue title and body first. The body should request a real,
reviewable repository change and include a unique marker.

```bash
REPOSITORY=$(gh repo view --json nameWithOwner --jq '.nameWithOwner')
ISSUE_URL=$(gh issue create --repo "$REPOSITORY" --title "<title>" --body "<request>")
ISSUE_NUMBER=${ISSUE_URL##*/}
gh issue view "$ISSUE_NUMBER" --repo "$REPOSITORY" --json number,title,state,author,labels,url
gh issue edit "$ISSUE_NUMBER" --repo "$REPOSITORY" --add-label ocint
systemctl --user list-timers ocint-daemon.timer --no-pager
```

Record `REPOSITORY`, `ISSUE_URL`, `ISSUE_NUMBER`, and the timer's next trigger
immediately. Wait for that trigger and confirm the service start timestamp came
from the timer invocation.

## Acceptance Anti-Patterns

Do not use these commands to advance a normal LCH acceptance run:

```bash
ocint daemon migrate
systemctl --user start ocint-daemon.service
systemctl --user start --no-block ocint-daemon.service
```

They bypass behavior that the exercise is intended to validate:

| Command | Hidden failure |
| --- | --- |
| `ocint daemon migrate` | Daemon startup may not run or may fail to migrate. |
| Manual service start | The timer may be disabled, misconfigured, or unable to trigger the service. |

If the expected timer deadline passes without a service start, diagnose the
timer rather than manually starting the service:

```bash
ocint daemon lch status
systemctl --user status ocint-daemon.timer --no-pager
systemctl --user list-timers ocint-daemon.timer --no-pager
systemctl --user cat ocint-daemon.timer
systemctl --user cat ocint-daemon.service
loginctl show-user "$USER" --property=Linger
```

A manual migration or service start is permitted only as an explicitly approved
diagnostic bypass after the corresponding failure is recorded. Report that the
bypassed acceptance criterion remains unverified.

## LCH And Logs

```bash
ocint daemon lch status
ocint daemon lch logs --lines 200
systemctl --user status ocint-daemon.service --no-pager
systemctl --user status ocint-daemon.timer --no-pager
```

Expected service states:

| State | Meaning |
| --- | --- |
| `inactive/dead`, result `success` | Previous cycle completed normally. |
| `activating/start` | The oneshot daemon is currently running. |
| `failed` | Inspect daemon logs and `systemctl --user status`. |
| Timer `active/waiting` | Future lifecycle invocations remain scheduled. |

For a successful automation check, the timer's recorded trigger must be followed
by a service start without a manual start command.

Useful daemon log milestones are `daemon cycle started`, `task created`, `job
scheduled`, `job started`, each `job stage`, `pull_request`, `task addressed`,
and `daemon cycle completed`.

## Database Trace

All queries are read-only. Never remove, replace, truncate, or recreate the
database during diagnosis.

### GitHub Mapping And Thread

```bash
sqlite3 -header -column "$DAEMON_DB" "
SELECT
  g.source_id,
  g.github_issue_id,
  g.issue_number,
  g.eligible,
  g.pull_request_number,
  g.pull_request_url,
  t.id AS thread_id,
  t.configured_repository,
  t.title
FROM github_issue AS g
LEFT JOIN thread AS t ON t.source_id = g.source_id
WHERE g.issue_number = $ISSUE_NUMBER;
"
```

### Messages And Classification

```bash
sqlite3 -header -column "$DAEMON_DB" "
SELECT
  m.id,
  m.source_id,
  m.actor,
  m.classification,
  m.source_created_at,
  substr(m.body, 1, 160) AS body
FROM thread_message AS m
JOIN thread AS t ON t.id = m.thread_id
JOIN github_issue AS g ON g.source_id = t.source_id
WHERE g.issue_number = $ISSUE_NUMBER
ORDER BY m.source_created_at, m.source_id;
"
```

### Task And Job

```bash
sqlite3 -header -column "$DAEMON_DB" "
SELECT
  task.id AS task_id,
  task.kind,
  task.state AS task_state,
  task.reason,
  task_job.attempt,
  job.id AS job_id,
  job.state AS job_state,
  job.stage,
  job.session_id,
  job.origin_kind,
  job.origin_source_thread_id,
  job.origin_source_anchor_id,
  job.worktree_path,
  job.branch,
  job.commit_sha,
  job.pushed,
  job.pull_request_url,
  job.publication_refusal,
  job.error,
  job.updated_at
FROM task
JOIN thread ON thread.id = task.thread_id
LEFT JOIN task_job ON task_job.task_id = task.id
LEFT JOIN job ON job.id = task_job.job_id
JOIN github_issue AS g ON g.source_id = thread.source_id
WHERE g.issue_number = $ISSUE_NUMBER
ORDER BY task.id, task_job.attempt;
"
```

Job stages normally progress through:

```text
execution -> validation -> commit -> push -> pull_request -> complete
```

The worktree and session checkpoints can be populated while the stage remains
`execution`. Use `updated_at`, logs, and OpenCode state to distinguish active
work from a stuck request.

## Worktree And Publication

Use the persisted values from the job query:

```bash
git -C "$WORKTREE_PATH" status --short --branch
git -C "$WORKTREE_PATH" diff --stat
git -C "$WORKTREE_PATH" log --oneline --decorate -5
git ls-remote --heads origin "refs/heads/$BRANCH"
gh pr list --repo "$REPOSITORY" --state all --head "$BRANCH" --json number,title,state,url,headRefName
gh issue view "$ISSUE_NUMBER" --repo "$REPOSITORY" --json labels,comments,state,url
```

Interpretation:

| Evidence | Interpretation |
| --- | --- |
| Clean worktree, execution active | Agent has not edited yet or request failed before tool use. |
| Local changes, execution active | Agent work is in progress. |
| Commit SHA, `pushed=0` | Commit succeeded; inspect push failure. |
| Remote branch, no mapped PR | Inspect publication stage and GitHub API failure. |
| `publication_refusal` set | The owned PR was closed or merged and will not be replaced. |
| PR URL set, unresolved task | Inspect completion reconciliation and issue reply. |

## OpenCode Diagnosis

Start with the persisted `session_id`. Avoid dumping complete transcripts or
private auth data.

```bash
sqlite3 -header -column "$OPENCODE_DB" "
SELECT
  id,
  title,
  directory,
  tokens_input,
  tokens_output,
  tokens_reasoning,
  cost,
  datetime(time_created / 1000, 'unixepoch') AS created,
  datetime(time_updated / 1000, 'unixepoch') AS updated
FROM session
WHERE id = '$SESSION_ID';
"

sqlite3 -header -column "$OPENCODE_DB" "
SELECT
  message.id,
  json_extract(message.data, '$.role') AS role,
  json_extract(message.data, '$.finish') AS finish,
  json_extract(message.data, '$.error.name') AS error,
  json_extract(part.data, '$.type') AS part_type,
  json_extract(part.data, '$.tool') AS tool,
  json_extract(part.data, '$.state.status') AS tool_status,
  length(json_extract(part.data, '$.text')) AS text_length
FROM message
LEFT JOIN part ON part.message_id = message.id
WHERE message.session_id = '$SESSION_ID'
ORDER BY message.time_created, message.id, part.time_created, part.id;
"

rg -n "$SESSION_ID|stream error|ERROR" "$OPENCODE_LOG"
```

The OpenCode database schema is internal. If these queries stop matching the
installed OpenCode version, inspect `.schema session`, `.schema message`, and
`.schema part` before adapting the read-only query.

### Compare Safe Configuration Fields

```bash
SOURCE_CONFIG="$HOME/.config/opencode/opencode.json"
jq '{model, serviceTier: .agent.build.options.serviceTier}' "$SOURCE_CONFIG"
jq '{model, serviceTier: .agent.build.options.serviceTier}' "$OPENCODE_CONFIG"
```

Normal OpenCode succeeding does not prove the restricted daemon configuration
will succeed. Compare required non-secret model and agent options. Never print
provider credentials or auth files.

When a missing option is strongly suspected, a minimal local probe can test the
hypothesis without changing generated configuration. Get approval before the
probe because it creates an OpenCode session and invokes the model:

```bash
timeout 45s env \
  XDG_CONFIG_HOME="$(dirname "$(dirname "$OPENCODE_CONFIG")")" \
  XDG_DATA_HOME="$OPENCODE_DATA" \
  OPENCODE_CONFIG_CONTENT='{"agent":{"build":{"options":{"serviceTier":"priority"}}}}' \
  opencode run --pure --format json \
  "Reply with exactly OK and do not call tools."
```

Treat this only as a diagnostic experiment. A successful override does not fix
the provisioned service.

## Failure Matrix

| First missing transition | Primary evidence | Likely causes |
| --- | --- | --- |
| Label to GitHub mapping | Issue JSON, daemon logs | Wrong label, closed issue, polling/API/token failure, wrong repository. |
| Mapping to eligible thread | `eligible`, actor | Actor not allowed or source no longer eligible. |
| Message to task | classification, task rows | Unauthorized/agent message, already covered message, reconciliation failure. |
| Task to running job | job state, service state | Scheduler capacity, stale recovery, service shutdown. |
| Job to worktree | job error, Git logs | SSH identity, mirror fetch, branch, filesystem permissions. |
| Worktree to assistant output | OpenCode log/session | Provider auth, rejected request, missing model option, server failure. |
| Execution to validation | OpenCode completion, daemon log | Agent still active, request retrying, completion observation failure. |
| Validation to commit | checks and job error | Repository checks failed or timed out. |
| Commit to push | commit SHA, remote branch | SSH/push rejection or remote conflict. |
| Push to PR | remote branch, publication fields | GitHub API failure or closed owned PR refusal. |
| PR to addressed task | PR URL, comments, task state | Reply failure or completion reconciliation failure. |

## Cleanup

Ask before changing remote artifacts:

```bash
gh issue edit "$ISSUE_NUMBER" --repo "$REPOSITORY" --remove-label ocint
gh issue close "$ISSUE_NUMBER" --repo "$REPOSITORY"
gh pr close <pr-number> --repo "$REPOSITORY"
```

Removing the label prevents new eligible work but does not necessarily cancel a
running job. Preserve all databases, worktrees, mirrors, logs, and generated
configuration. Restore timer/service state only if the exercise changed it.

## Report Template

```text
Repository:
Issue:
Task / attempt:
Job / session:
Worktree / branch:
PR:

Install and migration:
LCH timer and service:
Stages reached:
Final task/job state:
First broken transition:
Evidence:
Cause:
Retry behavior:
Artifacts created:
Cleanup performed:
```
