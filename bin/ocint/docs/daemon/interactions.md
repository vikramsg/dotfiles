# Daemon Interactions

ocint accepts repository work from configured GitHub issues and conversations
from configured Slack public channels. These are separate workflows that share
database infrastructure, not one shared execution lifecycle.

## GitHub Execution Lifecycle

```text
initial request -> work -> pull request -> completion reply
      ^                                      |
      `------------- follow-up --------------'
```

An authorized initial request starts work. When the work completes, ocint
creates or updates the thread's pull request and posts a completion reply.

An eligible follow-up reuses the existing OpenCode session, worktree, branch,
and pull request.

ocint's own GitHub replies do not schedule work. Unauthorized messages do not
become prompt input.

If the owned pull request is closed or merged, ocint does not create a
replacement.

## GitHub

An open issue with the configured label starts work.

- The issue title is the work title.
- The issue body and authorized comments become prompt input.
- A later authorized comment starts follow-up work.
- ocint replies using issue comments.
- Closing the issue or removing its configured label makes it ineligible.

After completing work, ocint replies:

```text
Issue addressed: <pull-request-url>

To make further changes, add a comment.
```

## Slack Coordinator Conversation

An ordinary authorized human root in a configured public channel starts one
coordinator conversation:

- The complete message becomes a coordinator turn.
- Authorized thread replies become later turns in source-message order.
- One Slack root maps to one coordinator OpenCode session.
- Coordinator output is posted inside the original Slack thread.
- Only the coordinator talks to Slack.
- Bot-authored and unauthorized messages are durably ignored and receive no
  coordinator execution.

```text
root message ---------------------> one coordinator session
    |                                          |
    +-- authorized reply ----------------------+
    |                                          v
    `-- coordinator numbered replies <---- full persisted response
```

A reply delivered before the root waits durably for that root; it does not run
OpenCode by itself. Edits, deletions, file-only messages, unsupported subtypes,
and unconfigured channels are also ignored. Slack retries are deduplicated by
provider event and message identity.

Long answers are preserved rather than truncated. The full OpenCode response
is stored, then split into ordered `[N/M]` chunks of at most 3,500 characters.
Posting observes the configured per-channel interval and durable `Retry-After`.
After an uncertain network result, recovery searches the thread for the
deterministic `client_msg_id` before posting again.

Phase 1 has no Slack reopening command because coordinator conversations do not
close into repository work. It also has no repository sandbox: the coordinator
can explain and research, but cannot create jobs, worktrees, commits, pushes, or
pull requests.
