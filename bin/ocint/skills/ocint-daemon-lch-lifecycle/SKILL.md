---
name: ocint-daemon-lch-lifecycle
description: Use when exercising or debugging the complete ocint daemon LCH lifecycle, from a labelled GitHub issue through task execution, pull-request publication, and issue reply.
---

# ocint Daemon LCH Lifecycle

Use this skill to run one observable, live issue-to-PR exercise or to locate the
stage where an existing daemon job stopped progressing.

Read [`references/diagnostics.md`](references/diagnostics.md) for exact commands,
SQL queries, expected states, and failure signatures.

## Safety

- Confirm the target repository and requested issue content before creating
  GitHub artifacts.
- Get explicit approval before creating a live test issue when the user has not
  already requested an end-to-end exercise.
- Record the issue number, task ID, job ID, session ID, branch, worktree, and PR
  URL as soon as each becomes available.
- Never print tokens, environment-file contents, auth files, or provider API
  keys.
- Never delete `.sqlite` or `.db` files. Preserve daemon configuration, logs,
  mirrors, worktrees, and OpenCode state while diagnosing failures.
- Do not close issues or PRs, remove labels, stop timers, or alter generated
  configuration unless the user requested it or approved cleanup.
- If a command changes lifecycle state, capture the initial state and restore it
  after the exercise unless the user wants the new state retained.

## Lifecycle

```text
install/provision
       |
       v
doctor + timer ready
       |
       v
open issue -> apply "ocint" label -> start/poll daemon
                                      |
                                      v
GitHub mapping -> thread -> message -> task -> job
                                             |
                                             v
                         worktree -> OpenCode -> validate
                                             |
                                             v
                              commit -> push -> pull request
                                             |
                                             v
                              issue reply -> task addressed
```

## 1. Establish The Run

Identify the repository, current revision, installed ocint executable, daemon
configuration, and existing LCH state. Decide whether this run needs
installation, reprovisioning, or only an already-installed lifecycle exercise.

Do not reinstall by default. Reinstall only when the user asks to test package
installation or when the installed executable is not the intended revision.

The preflight passes when:

- GitHub and SSH authentication are available;
- the configured repository is the intended target;
- the timer is installed and active;
- required configuration and credentials pass `ocint daemon doctor`;
- the database is at the expected migration after daemon startup;
- the configured OpenCode executable and policy are valid.

An occupied private OpenCode or API port is expected while the oneshot service
is running. Interpret port diagnostics together with systemd state rather than
calling an active daemon unhealthy solely because its ports are in use.

## 2. Create And Trigger Work

Create a narrowly scoped issue whose requested result is a meaningful repository
change. Include a unique correlation marker in the body. Create it without the
`ocint` label so the daemon cannot ingest incomplete setup.

After preflight:

1. Apply the `ocint` label.
2. Verify the issue is open, labelled, and authored by an allowed actor.
3. Let the timer invoke the service, or start the oneshot service with
   `systemctl --user start --no-block ocint-daemon.service` when immediate
   observation is required.
4. Do not start a second daemon process while the systemd service is active.

## 3. Trace State In Layers

Trace one identifier through every layer. Do not jump directly to the final PR
check because an absent PR says nothing about where execution stopped.

```text
GitHub issue number
  -> github_issue.source_id
  -> thread.id
  -> task.id
  -> task_job.job_id
  -> job.session_id / job.branch / job.worktree_path
  -> remote branch / pull request / issue reply
```

Inspect layers in this order:

1. **GitHub:** issue state, label, author, comments, and repository.
2. **LCH:** timer schedule, service state, migration, durable job status, and logs.
3. **Daemon database:** mapping, eligibility, message classification, task,
   attempt, job state, stage, checkpoints, refusal, and error.
4. **Worktree and Git:** local changes, commits, branch, remote branch, and push.
5. **OpenCode:** session creation, assistant output, tool activity, provider
   errors, and completion.
6. **Publication:** GitHub mapping, PR URL, issue response, and addressed task.

Poll using persisted state or explicit completion signals. Do not rely only on
fixed sleeps, and do not continuously stream logs when a targeted query will
answer the question.

## 4. Diagnose The First Broken Transition

Find the first transition whose input exists but output does not. Evidence from
later layers is secondary.

Examples:

- Label exists but no `github_issue`: polling, token, API, or repository policy.
- Mapping exists but `eligible=0`: actor authorization or issue eligibility.
- Thread exists but no task: message classification or task coverage policy.
- Job remains queued: scheduler, capacity, lifecycle, or stale recovery.
- Job fails before a worktree: mirror, SSH, branch, or filesystem provisioning.
- Job remains in execution with no assistant output: inspect the private
  OpenCode log and compare source versus effective model configuration.
- Commit exists but no remote branch: push authentication or transport.
- Remote branch exists but no PR: publication request, GitHub API, or an owned
  closed/merged PR refusal.
- PR exists but task is unresolved: completion reconciliation or reply failure.

For model failures, compare only non-secret fields such as model name,
`agent.build.options.serviceTier`, provider name, and selected model options.
LCH intentionally restricts global OpenCode configuration, so a required agent
option can be absent even when normal OpenCode requests succeed.

## 5. Decide Success Or Failure

Success requires all observable outcomes, not merely a completed process:

- job state is `completed` and stage is `complete`;
- the expected commit is on the remote job branch;
- a PR exists and the GitHub mapping stores its number and URL;
- the issue contains the idempotent addressed reply;
- the task is `addressed`;
- the service exits successfully and the timer remains active.

If the lifecycle fails, report the first broken transition, its identifiers,
direct evidence, likely cause, current retry behavior, and whether any remote
artifacts were created.

## 6. Cleanup And Report

Do not automatically erase evidence. For a failed run, ask whether to remove the
label to prevent future retries. Removing a label can abandon a queued job, but
a running job may continue until terminal.

Report:

- repository, issue, job, branch, session, and PR identifiers;
- install, provision, migration, timer, and service results;
- each lifecycle stage reached;
- final task and job states;
- created local and remote artifacts;
- exact failure evidence or confirmation of success;
- cleanup performed and lifecycle state restored.
