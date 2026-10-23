# Daemon Thread Tasks

## Purpose

The daemon turns an external discussion into Git work. The task core owns only
threads, messages, tasks, and daemon-job attempts. GitHub owns source identity,
routing, eligibility, and pull-request metadata behind a narrow source protocol.

## Model

```text
source adapter: routing + eligibility + provider mappings
                         |
                         v
thread (id, opaque globally unique source_id, optional title)
                         |
                         +-- ordered contributions
                         `-- tasks -- triggering messages -- job attempts
```

Every contribution is a `ThreadMessage`, including a GitHub issue's body. The
GitHub adapter maps that root message explicitly; task core does not need a
root/reply kind and never parses IDs such as `github:owner/repository:123`.
Messages have one of three classifications: `actionable`, `unauthorized`, or
`agent_response`. There is no separate actor-type field.

Thread and message source identifiers are globally unique opaque strings to the
core. GitHub emits `github:<owner/repository>:<issue-id>` for a thread,
`github:<owner/repository>:issue:<issue-id>` for its root message, and
`github:<owner/repository>:comment:<comment-id>` for comments. The root message
uses the issue's GitHub `created_at` timestamp, just like comments use theirs.

GitHub's mapping stores the configured repository name, GitHub repository and
issue IDs, root-message ID, eligibility, and pull-request metadata. The core
asks the source whether a thread is eligible and where it routes.

## Pending And Task Coverage

A message is pending exactly when it is actionable and is not attached to an
`unresolved` or `addressed` task. `skipped`, `rejected`, and `errored` tasks do
not cover messages. Task creation selects and attaches every pending message in
the same database transaction.

```text
actionable message
       |
       +-- covered by unresolved/addressed task -> not pending
       `-- uncovered or only skipped/rejected/errored -> pending
```

When a current attempt fails and new messages exist, reconciliation first skips
the old task and then recomputes pending messages. The successor therefore owns
both the messages released from the skipped task and the new messages. Without
new messages, another job attempt remains attached to the same task.

When a source becomes ineligible, a queued job is abandoned and its unresolved
task is skipped. A running job is allowed to finish and the task remains
unresolved during that run; reconciliation skips it once the job is terminal and
the source is still ineligible. If the source becomes eligible again, the skipped
task no longer covers its messages, so reconciliation creates a replacement
without requiring another comment.

SQLite task claiming starts with `BEGIN IMMEDIATE`. Competing reconcilers
therefore serialize the pending-message read and task/message inserts; the later
claim observes the first unresolved task's coverage instead of creating a
duplicate batch.

## Prompts And Artifacts

The canonical prompt contains the optional thread title and every actionable
message in source order. Unauthorized contributions and marker-identified agent
responses are excluded. A follow-up derives its reusable OpenCode session,
worktree, branch, and Git baseline from an addressed task's completed job; no
execution-artifact state lives on the thread.

The prompt requires meaningful repository changes because the daemon's output
contract is a pull request, not a private conversational response. Research and
informational requests are materialized in the most appropriate repository
documentation. OpenCode never publishes the pull request itself; validation,
commit, push, and publication remain daemon-owned stages.

## Edits

Messages are not versioned. Polling updates a stored message while it is not
covered by an addressed task. An edit does not itself create work: an unresolved
task still covers the edited message. Once an addressed task covers a message,
later source edits neither change stored content nor schedule work.

There is one unavoidable race: an edit made during a successful active attempt
can be missed if the poll observes it only after that attempt becomes addressed.
Users should add a new contribution when they need follow-up work.

## Reconciliation

```text
poll source -> update mappings and messages -> check eligibility
                                                  |
                    +-----------------------------+------------------+
                    |                                                |
                ineligible                                       eligible
                    |                                                |
        queued: abandon + skip                           reconcile current job
        running: wait; skip when terminal
                                                                     |
                       +------------------+--------------------------+-----------+
                       |                  |                                      |
                   completed           failed, no new                       failed + new
                       |                  |                                      |
              publish + address       retry task                 skip -> recompute -> successor
                       |
                 later pending messages -> follow-up using addressed artifact
```

Agent comments are recognized by both the configured agent identity and an
ocint marker. The GitHub adapter converts mapped root and comment messages into
marker anchors; task core never interprets their opaque source IDs. Merely
posting as the configured actor is not enough to exclude a human contribution.

## Migration

The provider-neutral schema migration deliberately performs no backfill. It
discards all existing thread workflow tables and rows, recreates them empty, and
preserves the `job` table and every job row. The first successful source poll
rebuilds threads, root messages, and comments; each uncovered actionable root
message is then pending and creates a task.
