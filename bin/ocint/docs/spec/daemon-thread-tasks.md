# Daemon Thread Tasks

## Purpose

The daemon turns an external discussion into Git work. Its workflow core is
provider-neutral: it owns threads, messages, tasks, and daemon-job attempts.
GitHub is currently an adapter that imports issues/comments and publishes pull
request outcomes. A future adapter may import another threaded discussion
without changing task reconciliation.

## Model

```text
source adapter
     |
     v
thread (configured repository, subject, body)
     |
     +-- ordered thread messages
     |
     `-- tasks
            |
            +-- triggering message batch
            `-- daemon-job attempts
```

A thread stores the configured ocint repository name directly. A message has a
source identity, actor, disposition, body, and source timestamp. The task core
does not inspect the source identity.

Each source synchronization also records whether a thread remains eligible for
work. A source adapter marks the threads it currently offers as eligible and
marks absent threads ineligible only after a successful complete poll. An
ineligible thread cannot create or retry tasks. If its current job is already
running, that job finishes normally; reconciliation then skips its unresolved
task with the reason `source thread is no longer eligible`.

A task is either `initial` or `follow_up`. It is `unresolved` until it is
addressed, rejected, explicitly errored, or skipped. A daemon job is one
execution attempt for a task. Jobs are immutable attempts: a retry creates a
new job instead of changing a failed job.

Once a task successfully publishes work, its job becomes the thread's canonical
execution artifact. Follow-up tasks inherit that job's OpenCode session,
worktree, branch, and Git baseline. This keeps every follow-up on the pull
request branch rather than only reusing the pull-request URL.

## Prompt

Every task attempt renders one canonical prompt:

```text
thread subject and body
  + every accepted human message in chronological order
```

The prompt includes messages from prior addressed and skipped tasks so an agent
always receives the complete accepted discussion. Agent responses and rejected
messages are never included.

## Reconciliation

```text
poll source -> upsert thread/messages -> reconcile
                                      |
                         +------------+-------------+
                         |                          |
                    no task                    unresolved task
                         |                          |
                         v                          v
                 create initial task         inspect current job
                                                    |
                  +---------------------------------+-----------------------+
                  |                                 |                       |
              running                         completed                  failed
                  |                                 |                       |
                  v                                 v                       v
                wait                    publish/reply, address       repoll messages
                                                                      |
                                              +-----------------------+-----------------------+
                                              |                                               |
                                       no new accepted messages                         new accepted messages
                                              |                                               |
                                              v                                               v
                                  new job for same task                        skip old task, create successor
                                  with inherited artifacts                     with batched new messages
```

New messages received while a daemon job is running remain unassigned until the
job reaches a terminal state. Reconciliation then repolls the source. A
completed task with unassigned accepted messages receives a follow-up task. A
failed task receives a new job attempt when there are no new messages; when
there are new messages, the old task is skipped with a durable reason and the
successor uses the prior job's session, worktree, branch, and baseline.

## Idle Lifecycle

```text
no running daemon jobs
          AND
no unresolved eligible tasks
          |
          v
start 60-second idle grace
          |
          +-- source poll or task reconciliation finds work -> reset grace
          `-- still idle -> stop daemon cycle
```

An error in a daemon job does not make the daemon idle. Reconciliation runs
before grace can begin and either starts another job attempt or creates a
successor task.

## Source Adapters

The core task tables intentionally contain no GitHub issue, pull request, or
comment fields. A source adapter maps its external thread and messages to the
generic model. The GitHub adapter retains GitHub identities, markers, and pull
request metadata in its own mapping tables. It publishes the final response only
after a task job completes its validation, commit, push, and pull-request work.
