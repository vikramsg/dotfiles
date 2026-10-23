# Daemon Interactions

ocint accepts work from configured GitHub issues and Slack channels. Each issue
or Slack root message represents one work thread.

## Shared Lifecycle

```text
initial request -> work -> pull request -> completion reply
      ^                                      |
      `------------- follow-up --------------'
```

An authorized initial request starts work. When the work completes, ocint
creates or updates the thread's pull request and posts a completion reply.

An eligible follow-up reuses the existing OpenCode session, worktree, branch,
and pull request.

ocint's own replies do not schedule work. Unauthorized messages do not become
prompt input.

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

## Slack

An ordinary root message in a configured private channel starts work.

- The first non-empty line is the work title.
- The complete root message becomes prompt input.
- Authorized thread replies become follow-up input while the thread is open.
- ocint replies inside the Slack thread.
- Unauthorized users receive a reply and do not schedule work.

After completing work, ocint:

1. Posts the pull-request result in the thread.
2. Adds the configured completion reaction to the root message.
3. Marks the Slack thread closed in daemon state.
4. Stops polling replies on that root message.

The default completion reaction is `white_check_mark`.

The completion reply must explain the Slack reopening protocol:

```text
Issue addressed: <pull-request-url>

ocint has stopped polling this Slack thread. To request further changes:

1. Copy the permalink of this thread's root message.
2. Post a new root message in this channel:

   reopen <root-message-permalink>

3. Reply in the new thread with your requested changes.

The reopen message alone does not schedule work.
```

### Reopening Slack Work

A reopen request must be a new, authorized, single-line root message:

```text
reopen <root-message-permalink>
```

The referenced root must:

- Be known to ocint.
- Be closed in daemon state.
- Belong to the same Slack workspace and channel.
- Belong to the same configured repository.
- Have no existing open alias.

A valid reopen request creates a new Slack thread representing the existing
work thread. A subsequent authorized reply in that new thread starts follow-up
work and reuses the existing execution context and pull request.

Replying directly to the closed Slack thread does not schedule work. Replies
added while it is closed are not recovered.

Malformed, unknown, or otherwise invalid authorized reopen requests do not
schedule work and currently receive no explanatory response.
