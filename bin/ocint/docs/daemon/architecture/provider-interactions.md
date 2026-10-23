# Provider Interactions

The pull-request daemon and conversational coordinator share infrastructure but
have separate provider contracts.

## GitHub Pull-Request Source

```text
GitHub issue/comment
  -> GitHub source adapter
  -> provider-neutral task reconciliation
  -> pull-request job
  -> GitHub publication and issue reply
```

GitHub owns issue observation, comments, and pull-request transport. Task and
job modules own authorization outcomes, durable work, retries, and execution
context reuse.

## Slack Coordinator

```text
Slack signed callback
  -> Slack signature and timestamp validation
  -> Slack payload translation and actor classification
  -> provider-neutral coordinator preparation
  -> durable event/turn commit
  -> acknowledgement and worker wakeup
  -> OpenCode correlation
  -> provider-neutral delivery intent
  -> Slack lookup/post adapter
```

The coordinator core knows only provider, workspace, channel, thread, actor,
message, and delivery identities. Slack owns timestamps, callback shapes,
signatures, public-channel policy, bot classification, API errors, deduplication
lookup, and provider-specific safe logs.

Phase 1 executes only public `channel` messages. The normal typed union also
parses private `group` messages, but translation marks them unsupported before
authorization. They are durably ignored even if deployed credentials have more
scope than the manifest requests.
