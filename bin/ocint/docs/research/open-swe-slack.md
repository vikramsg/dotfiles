# Open SWE Slack Integration

## Scope

This note describes LangChain's Open SWE Slack integration at commit
[`998b808`](https://github.com/langchain-ai/open-swe/tree/998b808484cad570890ea463cb5ff3c7d8cb43aa),
dated 2026-07-27. Open SWE changes quickly, so the commit is part of every
conclusion below.

The short version is that Slack is an outer adapter around a shared LangGraph
thread and run core. Slack delivers signed HTTP events, Open SWE turns a Slack
thread into a deterministic LangGraph thread, and the agent uses Slack tools to
reply. Open SWE does not define Slack SQL tables or ORM models. It persists
schemaless JSON values in LangGraph thread metadata and Store namespaces.

## Connection Model

Open SWE uses four Slack-facing protocols:

| Protocol | Direction | Purpose |
| --- | --- | --- |
| Slack Events API over HTTPS | Slack -> Open SWE | `app_mention`, direct messages, multiparty direct messages, and reaction events |
| Slack interactivity over HTTPS | Slack -> Open SWE | Block Kit option, plan approval, and workflow approval actions |
| Slack Web API over HTTPS | Open SWE -> Slack | Read threads and users; post, update, and react to messages; set assistant status |
| Slack OpenID Connect | Browser/dashboard <-> Slack | Link a Slack member ID and verified email to the logged-in GitHub account |

It does not use Socket Mode. The app manifest explicitly disables it and points
event and interactivity request URLs at the FastAPI backend. The documented bot
scopes cover mentions, channel/DM history, channel metadata, posting, reactions,
and user email. See the
[manifest and endpoint configuration](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/docs/INSTALLATION.md#L296-L403).

Bot operation and user linking are separate:

- `SLACK_BOT_TOKEN` authorizes Slack Web API calls.
- `SLACK_SIGNING_SECRET` authenticates incoming event and interaction bodies.
- `SLACK_BOT_USER_ID` and `SLACK_BOT_USERNAME` identify and strip mentions.
- `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`, and optional `SLACK_TEAM_ID` enable
  the independent OIDC account-linking flow.

The FastAPI composition root mounts Slack beside GitHub and Linear routes; the
LangGraph deployment loads that app through `langgraph.json`. See
[`agent/api/app.py`](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/agent/api/app.py#L32-L58)
and
[`langgraph.json`](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/langgraph.json#L1-L25).

## Event To Agent Flow

```text
Slack event
   |
   | POST /webhooks/slack
   | X-Slack-Signature + X-Slack-Request-Timestamp
   v
verify signature -> classify mention/DM/reaction -> acknowledge immediately
                                                   |
                                                   v
                                          FastAPI background task
                                                   |
                     conversations.info/replies + users.info
                                                   |
                                                   v
                        normalize Slack context and resolve repository/user
                                                   |
                 UUID(MD5(channel_id + ":" + thread_ts))
                                                   |
                                                   v
                     LangGraph thread metadata + durable agent run
                                                   |
                                                   v
                 agent slack_* tools -> Slack Web API -> thread reply
```

The event route first verifies Slack's HMAC signature and five-minute replay
window. It handles Slack URL verification, reaction feedback, app mentions,
DMs, selected untagged two-party replies, and ready-plan replies. Bot messages
are rejected to prevent loops. The route returns an accepted response and puts
the slower processing in a FastAPI background task. See
[`slack_routes.py`](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/agent/webhooks/slack_routes.py#L11-L166)
and the
[signature verifier](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/agent/utils/slack.py#L116-L141).

Processing then:

1. Derives one stable LangGraph `thread_id` from Slack `channel_id` and root
   `thread_ts` using a UUID-shaped MD5 digest. This makes every follow-up in the
   Slack thread address the same LangGraph conversation.
2. Reads channel metadata, thread replies, user profiles, linked GitHub login,
   and repository defaults.
3. Converts the selected Slack history and images into LangChain message content
   blocks and builds a Slack-aware prompt.
4. Upserts owner, source, repository, and Slack source context into LangGraph
   thread metadata.
5. Calls the shared `dispatch_agent_run` contract with `source="slack"` and a
   Slack-specific configurable payload.

The deterministic ID is implemented in
[`thread_ids.py`](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/agent/utils/thread_ids.py#L1-L9).
Prompt construction and dispatch are visible in
[`webhooks/slack.py`](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/agent/webhooks/slack.py#L329-L623).

The shared dispatcher creates a LangGraph run with a normal user message,
`multitask_strategy="interrupt"`, and synchronous checkpoint durability. An
explicit mention or DM interrupts the active run. Slack has one deliberate
exception: an untagged follow-up on a busy thread goes into the shared Store
queue and is injected before the next model call. See
[`dispatch.py`](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/agent/dispatch.py#L107-L176),
[`_dispatch_or_queue_slack_run`](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/agent/webhooks/slack.py#L112-L157),
and the
[queue middleware](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/agent/middleware/check_message_queue.py#L148-L248).

## Runtime Connection Back To Slack

The Slack coordinates travel in LangGraph run configuration, not agent state:

```python
configurable = {
    "repo": {"owner": "...", "name": "..."},
    "slack_thread": {
        "channel_id": "C...",
        "channel_context": {
            "id": "C...",
            "name": "...",
            "name_normalized": "...",
            "topic": "...",
            "purpose": "...",
            "description": "...",
        },
        "thread_ts": "...",
        "triggering_user_id": "U...",
        "triggering_user_name": "...",
        "triggering_user_email": "...",
        "triggering_event_ts": "...",
    },
    "user_email": "...",
    "github_login": "...",  # when mapped
    "source": "slack",
}
```

Agent tools call `get_config()`, read `configurable.slack_thread`, and invoke the
Slack Web API. `slack_thread_reply` posts `chat.postMessage`, appends an Open SWE
Web link, and stores the resulting Slack message-to-run mapping. The status
middleware uses the same coordinates for `assistant.threads.setStatus`, refreshing
it during model and tool calls and clearing it after the run. See
[`slack_thread_reply.py`](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/agent/tools/slack_thread_reply.py#L19-L77)
and
[`refresh_slack_status.py`](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/agent/middleware/refresh_slack_status.py#L76-L217).

The default agent always has both Slack and Linear tools. Tools fail cleanly
when their source-specific config is absent rather than being selected per
source. See the
[tool registration](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/agent/server.py#L910-L940).

## Types

Open SWE has only a few explicit Slack types:

| Type | Shape and role |
| --- | --- |
| `SlackIdentity` | Frozen dataclass with `user_id`, `team_id`, optional `email`, `email_verified`, and optional `name`; validates OIDC user-info results |
| `SlackChannelContext` | Alias for `dict[str, str]`; normalized channel ID/name/topic/purpose/description |
| `ReviewerSlackThread` | Optional-key `TypedDict` with only `channel_id` and `thread_ts` |
| `MappingSource` / `MappingStatus` | Literals currently restricted to `slack_oauth` and `active | pending` |

`SlackIdentity` is defined in
[`dashboard/slack_oauth.py`](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/agent/dashboard/slack_oauth.py#L44-L88),
and `ReviewerSlackThread` in
[`review/findings.py`](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/agent/review/findings.py#L179-L197).

Most important contracts are not modeled. Incoming events, normalized
`event_data`, `slack_thread` config, Slack Web API responses, thread metadata,
Store values, and tool results are `dict[str, Any]`. There is no common
`SourceContext` union, `SlackThread` model, or provider protocol. The source
adapter and consumers agree on string keys. This keeps adapters easy to extend,
but makes key drift and incomplete metadata runtime concerns.

## Persistence Models

There are no application-owned Slack DB tables, migrations, SQLAlchemy models,
or Pydantic persistence models. LangGraph owns the physical database. Open SWE
uses its logical Thread and Store APIs as follows.

### LangGraph thread

The LangGraph thread is the durable conversation and checkpoint identity. Its
metadata includes generic fields:

```python
{
    "source": "slack",
    "repo": {"owner": "...", "name": "..."},
    "repo_owner": "...",
    "repo_name": "...",
    "github_login": "...",
    "triggering_user_email": "...",
    "title": "...",
    "created_at_ms": 0,
    "updated_at_ms": 0,
    "source_context": {"slack_thread": { ... }},
}
```

`source_context.slack_thread` contains the run-config fields above and may gain
a Slack permalink. Plan state, latest run status, and completion-reply dedupe
also live in thread metadata. The generic owner metadata upsert is shared by
Slack, Linear, and GitHub; only the nested source context differs. See
[`upsert_agent_thread_owner_metadata`](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/agent/webhooks/common.py#L720-L780).

### Store namespaces

| Namespace and key | Value | Purpose |
| --- | --- | --- |
| `("slack_run_map", channel_id)`, `thread:<thread_ts>` | `run_id`, `thread_ts`, optional `triggering_user_id`, optional `trace_message_ts` | Resolve a Slack thread to its latest LangGraph run |
| `("slack_run_map", channel_id)`, `message:<message_ts>` | Thread mapping plus `message_ts` | Resolve feedback on a bot message to its run |
| `["user_mappings"]`, lower-case GitHub login | `github_login`, `work_email`, optional `slack_user_id`, `source`, `status`, timestamps | Bidirectional GitHub/email/Slack identity link |
| `("slack_reaction_state", channel_id)`, `<run>:<user>:<message>` | `run_id`, `user_id`, `message_ts`, active reaction list | Current feedback state |
| `("slack_reaction_events", channel_id)`, Slack event ID | Event ID | Reaction-event idempotency |
| `("queue", thread_id)`, `pending_messages` | FIFO `messages` list, capped at 100 | Mid-run follow-ups; shared with dashboard and other integrations |

The exact mapping implementation is in
[`utils/slack.py`](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/agent/utils/slack.py#L1122-L1285),
the identity record in
[`dashboard/user_mappings.py`](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/agent/dashboard/user_mappings.py#L1-L39),
and reaction state in
[`utils/slack_feedback.py`](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/agent/utils/slack_feedback.py#L25-L105).

The OIDC access token is used only to fetch the verified Slack identity; it is
not persisted. The resulting identity is merged into the user mapping keyed by
the already authenticated GitHub login. See the
[OAuth callback](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/agent/dashboard/routes.py#L604-L665).

## Generic And Slack-Specific Boundaries

### Generic core

- FastAPI composition and background task execution.
- LangGraph thread, Store, checkpoint, and run APIs.
- Deterministic external-conversation-to-thread identity as a pattern, although
  each provider has its own ID function.
- `dispatch_agent_run`: content blocks plus configurable context, interrupt
  semantics, synchronous durability, and optional completion webhook.
- Generic owner metadata: source, repository, GitHub identity, title, timestamps,
  and nested `source_context`.
- Shared message content blocks, multimodal image preparation, model selection,
  repository parsing/defaults, account mapping, sandbox, and agent graph.
- Store-backed follow-up queue and before-model injection.
- Run-completion failure routing selected by `metadata.source` and
  `metadata.source_context`.

### Slack adapter

- Slack HMAC envelope verification, URL challenge, Event API classification,
  bot-loop prevention, and Block Kit form parsing.
- Channel/thread timestamp identity and the Slack-to-LangGraph UUID function.
- Mention, DM, untagged-thread, and plan-approval policies.
- Slack history windowing, mrkdwn formatting, mention syntax, Block Kit blocks,
  private-file fetching, channel topic/purpose interpretation, and Slack links.
- Bot token, app identity, scopes, API methods, retries, rate limits, and
  assistant-status heartbeat.
- `configurable.slack_thread`, Slack tools, run/message mapping, reaction feedback,
  and Slack OIDC account linking.

There is no Python `Protocol` separating a provider adapter from the generic
core. The practical integration contract is the combination of
`dispatch_agent_run(thread_id, content, configurable, source=...)`, LangGraph
thread metadata, and conventions for `source_context`. The completion handler
demonstrates this convention by branching on `source` and extracting Slack,
Linear, or GitHub coordinates from metadata. See
[`completion.py`](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/agent/completion.py#L133-L172).

## Notable Tradeoffs

- FastAPI `BackgroundTasks` gives Slack a fast acknowledgement but is not a
  durable queue. A process failure after the HTTP response can lose mention
  processing; ordinary mention events have no application-level event-ID dedupe.
- The deterministic thread ID omits Slack workspace/team ID. That is sufficient
  for the documented single-workspace app, but is not a safe multi-workspace key.
- Slack run and reaction records are schemaless and have no explicit migration
  path. Readers defensively inspect every field at runtime.
- The checked-in app manifest subscribes to mentions and DM events but not
  `reaction_added` or `reaction_removed`, even though the route implements both.
  It also lists `reactions:write`, not the `reactions:read` scope needed for
  reaction events. Reaction feedback therefore requires extending the published
  manifest. Compare the
  [manifest](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/docs/INSTALLATION.md#L351-L359)
  with the
  [reaction handlers](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/agent/webhooks/slack_routes.py#L42-L60).

## Lessons For Ocint

Open SWE validates the main boundary already used by the daemon: provider
adapters should translate external messages into provider-neutral durable
threads/tasks, while execution should not know how Slack signatures or mrkdwn
work. Its strongest reusable ideas are deterministic conversation identity,
fast webhook acknowledgement, durable run dispatch, source coordinates retained
for replies, and explicit provider-to-run mappings for feedback.

If Slack is added to `ocint`, preserve the existing typed architecture rather
than copying Open SWE's schemaless contracts:

1. Keep Slack event payloads, IDs, Block Kit actions, API calls, and rendering in
   a Slack adapter.
2. Map Slack `(workspace, channel, root thread timestamp)` to the existing
   provider-neutral `thread`; include workspace because `channel_id` is not a
   global tenant key.
3. Persist an explicit source-thread row and source-message idempotency key in
   SQLite. Do not derive application identity solely from MD5 or bury source
   coordinates in unvalidated metadata.
4. Pass a typed task request to the existing coordinator. Keep Git/OpenCode/job
   execution unchanged.
5. Model reply and reaction correlation explicitly if feedback is required.
6. Treat Slack OIDC identity linking as a separate optional capability from bot
   installation and event delivery.
7. Define a narrow outbound reply gateway shared by GitHub and Slack only when
   their actual semantics overlap. Keep mrkdwn, Block Kit, assistant status, and
   Slack rate-limit behavior behind the Slack implementation.

Open SWE's current code and installation guide disagree on one authentication
detail: the guide says an unmapped Slack user can run with limited installation
permissions, while the webhook implementation blocks a run without a valid
linked user GitHub token unless bot-token-only mode is enabled. For design work,
follow the pinned implementation at
[`webhooks/slack.py` lines 486-530](https://github.com/langchain-ai/open-swe/blob/998b808484cad570890ea463cb5ff3c7d8cb43aa/agent/webhooks/slack.py#L486-L530),
not the stale prose.
