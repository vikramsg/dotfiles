# Thread Outcome Architecture

Status: proposed

## Problem

The daemon currently models every accepted thread task as repository work:

```text
GitHub thread
      |
      v
OpenCode execution
      |
      v
validate -> commit -> push -> pull request -> issue comment
```

That model cannot represent a useful answer which does not require a repository
change. Questions, requests for clarification, and investigations are forced
through a pull-request workflow even when there is nothing appropriate to
commit.

The model needs two successful outcomes:

```text
                         +--> Reply(text) ---------> issue comment
                         |
thread task -> execution +
                         |
                         +--> Change(summary) ----> validate -> pull request
```

The outcome is part of task execution, not a GitHub-specific concept. GitHub is
only the first provider which publishes it.

## Decision

OpenCode should complete a task through a structured, typed completion contract.
The contract is a discriminated union with `reply` and `change` variants. The
daemon persists the result before it starts publication and validates that the
declared result agrees with repository state.

Conceptually:

```text
ThreadOutcome =
    ReplyOutcome {
        kind: "reply"
        body: non-empty Markdown
    }
  | ChangeOutcome {
        kind: "change"
        summary: non-empty text
    }
```

The completion mechanism should be a daemon-owned structured tool exposed to
the OpenCode session, not JSON embedded in the assistant's prose and not a file
inside the target repository. The exact OpenCode extension mechanism needs a
small compatibility spike before implementation. The required semantic API is:

```text
complete_thread({ kind: "reply", body: "..." })

complete_thread({ kind: "change", summary: "..." })
```

The daemon remains authoritative. A tool call records the model's intended
outcome, while Git checks enforce the outcome's preconditions:

```text
                         declared outcome
                                |
                   +------------+------------+
                   |                         |
                   v                         v
             kind = reply              kind = change
                   |                         |
          require clean worktree     require repository diff
                   |                         |
                   v                         v
             persist reply           persist change result
                   |                         |
                   v                         v
           publish comment       validate -> commit -> push -> PR
```

An inconsistent result fails explicitly. The daemon must not silently convert a
reply into a pull request or a change into a reply:

```text
reply + dirty worktree  -> failed: reply outcome produced repository changes
change + clean worktree -> failed: change outcome produced no repository changes
missing completion      -> failed: execution ended without a thread outcome
```

This rule keeps routing deterministic and makes model mistakes visible and
retryable.

## Why This Model

### Intent And Evidence Are Separate

The structured outcome captures intent. Git state supplies evidence. Neither is
sufficient alone:

```text
                    Intent             Evidence
                    ------             --------
Reply outcome       answer directly    worktree is clean
Change outcome      publish changes    worktree has a diff
```

Using both gives the daemon a stable decision and an independent consistency
check. It also avoids assigning product meaning to incidental filesystem state.

### The Decision Uses Full Context

The same OpenCode execution can inspect the thread, repository, prior session,
and current worktree before choosing an outcome. This matters for requests such
as "Is this already supported?":

```text
request -> inspect current code -> already supported -> Reply
                              \
                               -> missing behavior -> Change
```

A classifier which runs before repository inspection cannot reliably make that
decision.

### The Result Is Durable Before Side Effects

Publication can be retried after a process restart without asking the model to
decide again:

```text
execution -> persist outcome -> process stops
                              |
                         process restarts
                              |
                              v
                    read persisted outcome
                              |
                  +-----------+-----------+
                  |                       |
             post reply              publish PR
```

This follows the existing checkpointed job design and keeps external side
effects idempotent.

## Alternatives Considered

### Infer The Outcome From Git State

Rule:

```text
clean worktree -> reply with final assistant text
dirty worktree -> create a pull request
```

Advantages:

- Minimal new protocol surface.
- Repository state is easy to inspect.

Disadvantages:

- Incidental edits become a product-level routing decision.
- A model can answer a question while leaving scratch changes and accidentally
  trigger a pull request.
- A model can intend a change but fail to edit, causing an authoritative-looking
  reply instead of a visible failure.
- The assistant's final prose is not necessarily a publication contract.
- There is no explicit persisted explanation of why a path was selected.

Conclusion: use Git state as validation evidence, not as the routing decision.

### Classify Before Execution

Rule:

```text
thread -> classifier -> reply worker or change worker
```

Advantages:

- The selected path is explicit before expensive work starts.
- Reply tasks could avoid provisioning a worktree in obvious cases.

Disadvantages:

- The classifier lacks repository evidence unless it duplicates the execution
  environment and tools.
- Ambiguous requests require a second decision after investigation anyway.
- It adds model latency, cost, and another retry/idempotency boundary.
- Classification and execution can disagree.

Conclusion: do not make pre-classification authoritative. A future optional fast
path may classify requests which provably need no repository context, but it
must produce the same typed outcome and may not bypass authorization.

### Parse The Final Assistant Message

Rule:

```text
final text begins with REPLY:  -> reply
final text begins with CHANGE: -> pull request
```

Advantages:

- No custom tool is required.

Disadvantages:

- Prose parsing is fragile under formatting, truncation, and model changes.
- Control data leaks into user-facing text.
- Recovery must distinguish intermediate assistant messages from terminal
  control output.
- Schema evolution becomes string parsing.

Conclusion: acceptable only as a short-lived prototype. The production
contract should be schema-validated at the boundary.

### Require An Explicit Label Or Command

Rule:

```text
ocint-reply label -> reply
ocint-change label -> pull request
```

Advantages:

- Fully deterministic and easy to audit.

Disadvantages:

- Moves a decision the agent can make after investigation back to the user.
- A user often does not know whether a repository change is needed.
- Follow-up comments may need a different outcome from the root issue.

Conclusion: useful as an override, not as the default model.

## Domain Model

Task state and publication outcome should remain separate:

```text
TaskState
  unresolved -> addressed
             -> rejected
             -> errored
             -> skipped

TaskOutcome
  pending -> reply
          -> change
```

`addressed` means the selected outcome was successfully published. It does not
mean that a pull request exists.

The durable execution result should belong to the job attempt:

```text
job
 +-- state
 +-- stage
 +-- outcome_kind       pending | reply | change
 +-- outcome_body       reply Markdown or change summary
 +-- pull_request_url   populated only after change publication
```

The database must constrain valid combinations where practical. Service-layer
construction should use typed variants so invalid combinations are not passed
through the application as unrelated nullable fields.

## Workflow

### Execution

```text
create/reuse worktree and session
              |
              v
submit thread prompt
              |
              v
OpenCode investigates and optionally edits
              |
              v
complete_thread(Reply | Change)
              |
              v
daemon validates outcome against Git state
              |
              v
persist outcome checkpoint
```

The prompt should explain the available outcomes without prescribing one. It
must state that replies are for complete answers, not a way to avoid requested
implementation work.

### Publication

```text
persisted outcome
       |
       +-- reply ----> post issue comment with idempotency marker
       |
       +-- change ---> validate -> commit -> push -> find/create PR
                                              |
                                              v
                                  post issue comment with PR URL
```

Reply comments need their own marker outcome, for example `replied`, so polling
classifies them as agent responses and never schedules them as follow-up work.

### Follow-Ups

Every task batch chooses independently. A thread can therefore move between
outcomes without changing identity:

```text
root issue        -> Change -> PR #10
follow-up comment -> Reply  -> explanatory comment
follow-up comment -> Change -> update PR #10
```

A reply must not close or replace an existing owned pull request. A later change
continues to use the existing session, branch, and open pull request under the
current ownership rules.

## Failure And Recovery Rules

```text
Failure point                    Recovery
-------------                    --------
before outcome checkpoint        resume/observe OpenCode execution
after outcome checkpoint         do not ask OpenCode to decide again
during reply publication         find marker, then post only if absent
during change publication        reuse branch and find existing open PR
closed owned PR + new change      report existing closed-PR error policy
closed owned PR + new reply       allow reply; no PR mutation is required
```

The last distinction is important: PR availability is a precondition of change
publication, not thread eligibility in general.

## API Shape

Job status should expose one typed result rather than requiring callers to infer
it from `pull_request_url`:

```json
{
  "outcome": {
    "kind": "reply",
    "body": "The setting is already enabled."
  }
}
```

or:

```json
{
  "outcome": {
    "kind": "change",
    "summary": "Add reply-aware task publication",
    "pull_request_url": "https://github.example/pull/10"
  }
}
```

While a job is running, the outcome is explicitly `pending`; an empty URL is not
used as a hidden state signal.

## Implementation Plan

### Phase 1: Verify Structured Completion

1. Build a narrow spike against the pinned OpenCode version.
2. Prove that a daemon-owned tool can receive a schema-validated discriminated
   union and that its call can be recovered from session history.
3. Verify behavior after SSE disconnect, daemon restart, duplicate tool calls,
   and terminal assistant completion without a tool call.
4. Record the selected OpenCode extension API in the daemon documentation.

Do not change publication behavior in this phase. If the pinned OpenCode API
cannot provide durable structured tool calls, use schema-constrained structured
output as the fallback and document its recovery semantics before proceeding.

### Phase 2: Add The Durable Outcome Model

1. Introduce backend-neutral `ReplyOutcome` and `ChangeOutcome` types.
2. Add an Alembic migration for the pending/reply/change job result.
3. Add one checkpoint operation which atomically stores the selected variant and
   advances the execution stage.
4. Expose the typed result through the job API.
5. Keep existing pull-request fields during migration only where external API
   compatibility requires them.

### Phase 3: Route And Validate

1. Update the task prompt to describe both valid completion outcomes.
2. Accept exactly one terminal completion for each managed prompt.
3. Check declared outcome against worktree status and `HEAD` versus the persisted
   base revision.
4. Route replies directly to completion and changes into existing validation.
5. Fail inconsistent or missing outcomes with actionable errors.

### Phase 4: Publish Replies

1. Add an idempotent `replied` GitHub response marker.
2. Publish the persisted reply body verbatim, followed by the hidden marker.
3. Mark the task addressed only after the comment is observed or created.
4. Ensure polling classifies reply comments as agent responses.
5. Permit replies when an older owned pull request is closed or merged.

### Phase 5: Validate End To End

Required scenarios:

```text
question, no edits                    -> one reply, no branch or PR
implementation request with edits     -> validation and PR
reply declared with edits              -> explicit failure
change declared without edits          -> explicit failure
restart after reply checkpoint         -> one reply, no re-execution
restart during PR publication          -> one reused PR
reply after existing PR                -> reply, PR unchanged
change after reply                     -> PR created
agent reply observed by next poll      -> no follow-up task
unauthorized request                   -> unchanged authorization behavior
```

## Rollout

Keep the existing PR-only path as the operational default until the structured
completion spike and recovery tests pass. Then enable both outcomes together;
do not temporarily route based only on clean versus dirty Git state. A
configuration rollback can force all accepted work through `change`, but stored
outcomes remain readable so in-flight jobs can finish deterministically.

The architecture is complete when a reply is a first-class successful task
result, not a special case represented by the absence of a pull request.
