# Provider Interactions

This document shows why GitHub polling and Slack Events remain thin input
adapters while their workflows own different outcomes. Phase 1 does not route
Slack into the pull-request task coordinator.

## Boundary

The GitHub task core owns pull-request outcomes, task lifecycle, retries, and
execution-context reuse. The Slack coordinator core owns conversations, turns,
response persistence, and delivery recovery. Providers own transport identity,
authentication, and API behavior.

Platform responsibilities include API transport, message identity,
idempotency markers, and instructions required to continue work on that
platform.

## GitHub Task Contract

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
             `-> GitHubThreadSource.deliver()
                  -> append GitHub protocol guidance
                       "To make further changes, add a comment."
                  -> add hidden idempotency marker
                  -> GitHubTransport.post_comment()
  -> TaskRepository.set_state(ADDRESSED)
```

GitHub receives:

```text
Work addressed: <pull-request-url>

To make further changes, add a comment.
```

## Observation Call Stack

```text
Daemon
  -> TaskCoordinator.reconcile()
  -> SourceRouter.observe()
       |
       `-> GitHubThreadSource.observe()
            -> GitHub protocol: open labelled issues and comments
            -> ThreadObservation
  -> TaskCoordinator
       -> persist normalized messages
       -> create INITIAL or FOLLOW_UP task
       -> reuse existing execution context when available
```

## Slack Coordinator Call Stack

Slack does not implement the `ThreadSource` task contract in Phase 1. Events
are translated into provider-neutral coordinator messages, and only
coordinator output returns through the Slack adapter:

```text
POST /slack/events
  -> verify raw-body signature, timestamp, body size, workspace
  -> Slack event translator
  -> authorization and bot-loop policy
  -> CoordinatorRepository.ingest()
       -> commit event + message + conversation + eligible turns
  -> 200 response

Coordinator worker
  -> claim oldest eligible turn
  -> create/reuse restricted OpenCode session
  -> persist prompt intent -> observe/submit -> persist full response
  -> persist numbered delivery chunks
  -> SlackCoordinatorDelivery
       -> find deterministic client_msg_id after uncertain delivery
       -> post missing chunk to original root thread
       -> persist receipt or durable retry deadline
```

The coordinator contract contains provider, workspace, channel, thread,
message, actor, text, and source order. It does not contain Slack headers,
signatures, retry metadata, bot tokens, or raw event envelopes. This keeps
ingestion replaceable without turning Slack transport details into workflow
state.
