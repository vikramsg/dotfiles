# Daemon Interactions

## GitHub Pull-Request Work

An open issue with the configured label starts work. Its body and authorized
comments become prompt input. The daemon creates or updates the owned pull
request and replies on the issue. A later authorized comment reuses the existing
OpenCode session, worktree, branch, and pull request. Closing the issue or
removing the label makes it ineligible; closed or merged owned pull requests are
not replaced.

## Slack Coordinator

The Slack coordinator is independent of GitHub pull-request jobs. Slack sends a
signed `message.channels` callback for each public-channel root or reply. After
signature, workspace, channel, actor, and payload validation, ocint stores the
event before returning success. The worker serializes turns per thread, reuses
the thread's OpenCode session, and posts chunked responses back to that thread.

Only configured public `channel` messages from configured human actors are
executable in Phase 1. Bot, xoxp-originated, changed, empty, unconfigured,
unauthorized, and private `group` messages are durably ignored. Duplicate
callbacks and response retries do not create duplicate turns or replies.
