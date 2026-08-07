# Provider Interactions

This document defines the target call stack for provider-neutral interaction
coordination and thin platform adapters.

## Boundary

The core owns outcomes, shared prose, task lifecycle, retries, and execution
context reuse. Providers own only their platform protocols.

Platform responsibilities include API transport, message identity,
idempotency markers, reactions, and instructions required to continue work on
that platform.

## Shared Contract

Raw reply text is replaced with typed domain replies:

```python
ThreadReply = (
    AddressedReply
    | UnauthorizedReply
    | ClosedPullRequestReply
)
```

```python
class ThreadSource(Protocol):
    async def observe(self) -> ThreadObservations: ...
    async def deliver(self, reply: RenderedThreadReply) -> ObservedMessage: ...
```

`AddressedReply` carries the pull-request URL. `UnauthorizedReply` carries the
actor. `ClosedPullRequestReply` needs no unrelated text. Typed replies prevent
an outcome from being paired with the wrong message.

## Completion Call Stack

```text
PullRequestJob completes
  -> TaskCoordinator._complete()
  -> AddressedReply(pull_request_url)
  -> ThreadReplyService.send()
       -> CoreReplyRenderer.render()
            "Work addressed: <pull-request-url>"
       -> SourceRouter.deliver()
            |
            +-> GitHubThreadSource.deliver()
            |    -> append GitHub protocol guidance
            |         "To make further changes, add a comment."
            |    -> add hidden idempotency marker
            |    -> GitHubTransport.post_comment()
            |
            `-> SlackThreadSource.deliver()
                 -> append Slack protocol guidance
                 -> SlackTransport.post_message()
                 -> SlackTransport.add_reaction()
                 -> SlackRepository.close()
  -> TaskRepository.set_state(ADDRESSED)
```

Slack receives:

```text
Work addressed: <pull-request-url>

ocint has stopped polling this Slack thread. To request further changes:

1. Copy the permalink of this thread's root message.
2. Post a new root message in this channel:

   reopen <root-message-permalink>

3. Reply in the new thread with your requested changes.

The reopen message alone does not schedule work.
```

## Observation Call Stack

```text
Daemon
  -> TaskCoordinator.reconcile()
  -> SourceRouter.observe()
       |
       +-> GitHubThreadSource.observe()
       |    -> GitHub protocol: open labelled issues and comments
       |    -> ThreadObservation
       |
       `-> SlackThreadSource.observe()
            -> Slack protocol: roots, replies, reopen commands and aliases
            -> ThreadObservation
  -> TaskCoordinator
       -> persist normalized messages
       -> create INITIAL or FOLLOW_UP task
       -> reuse existing execution context when available
```

## Slack Reopening

Slack reopening remains entirely inside the Slack adapter:

```text
Slack history
  -> recognize reopen command
  -> validate referenced closed root
  -> map new physical root to existing logical thread ID
  -> suppress command as prompt input
  -> emit later replies as normal ACTIONABLE messages
```

The shared coordinator never knows that reopening occurred.
