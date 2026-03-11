# Codex CLI `/fast` -> API behavior and OpenCode mapping

## 1) Purpose and scope

This document captures how Codex CLI `/fast` works at the API payload level, and how to replicate equivalent behavior in OpenCode without guessing. It focuses on implementation evidence from source and docs, not roadmap decisions. [R1][R2][R3][R4][W1][W2]

## 2) Executive summary

- `/fast` is a built-in Codex slash command handled in the TUI command dispatcher, including `on|off|status` argument handling. [R1]
- `/fast` does **not** use a dedicated endpoint; Codex keeps using the standard Responses API path (`responses`) and the Responses WebSocket `response.create` flow. [R3][R4][R5]
- The effective API control is a request payload field: `service_tier`. [R5]
- Internal Codex `ServiceTier::Fast` is mapped to wire value `"priority"` in request construction. [R2]
- OpenCode already exposes equivalent payload control (`serviceTier` provider option serialized to `service_tier`), so a functional equivalent can be implemented either with plugin hooks or with static per-agent config. [R9][R10][R12]

## 3) Codex command-side behavior

### 3.1 Built-in command behavior

Codex declares `/fast` as a built-in slash command and supports inline args for this command class. [R6]

In `dispatch_command`, plain `/fast` toggles between:

- `None` (off)
- `Some(ServiceTier::Fast)` (on) [R1]

In `dispatch_command_with_args`, `/fast` supports:

- `on` -> set `Some(ServiceTier::Fast)`
- `off` -> set `None`
- `status` -> prints current state
- invalid args -> usage error (`/fast [on|off|status]`) [R1]

### 3.2 Session context and persistence

When toggled, Codex emits an `OverrideTurnContext` op carrying `service_tier: Some(service_tier)` so subsequent turns inherit the choice, and separately emits `PersistServiceTierSelection` to save preference. [R1][R7][R8]

`PersistServiceTierSelection` is handled by app code that writes config via `ConfigEditsBuilder::set_service_tier(...)` and reports success/failure in UI. [R8]

## 4) API-level behavior (what actually changes on the wire)

### 4.1 No special endpoint

Codex uses the regular Responses API flow:

- HTTP/SSE client posts to `responses` path
- WebSocket flow sends `response.create` payload over Responses WS [R3][R4]

No separate `/fast` endpoint is introduced in this path. [R3][R4]

### 4.2 Payload field that controls speed tier

The request structs include optional `service_tier`:

- `ResponsesApiRequest.service_tier: Option<String>`
- `ResponseCreateWsRequest.service_tier: Option<String>` [R5]

Codex request construction maps internal tier to payload value:

```rust
service_tier: match service_tier {
    Some(ServiceTier::Fast) => Some("priority".to_string()),
    Some(service_tier) => Some(service_tier.to_string()),
    None => None,
}
```

So `/fast` is implemented by mutating `service_tier` in the Responses request payload. [R2][R5]

### 4.3 Same behavior across transports

For HTTP/SSE, Codex serializes `ResponsesApiRequest` and sends it to `responses`. [R3]

For WS, Codex converts the request into `ResponseCreateWsRequest` and sends `ResponsesWsRequest::ResponseCreate(...)`; `service_tier` is preserved in this conversion path. [R2][R4][R5]

## 5) Why this explains observed behavior

Reports that "fast mode isn't active by default unless `service_tier=fast` is configured" align with this design: config/session tier drives per-turn request construction, which then drives payload `service_tier`. [R11][I1]

## 6) OpenCode equivalence (current capability)

OpenCode exposes equivalent control knobs:

- Static agent config can set `agent.<name>.options.serviceTier`, and OpenCode merges `agent.options` into runtime LLM options before request send. [R12]
- Plugin hook `"chat.params"` can mutate request options before model call. [R9]
- OpenAI Responses provider maps `providerOptions.openai.serviceTier` to request `service_tier`. [R10]
- Supported OpenCode values there are `auto | flex | priority`. [R10]

Therefore, Codex `/fast` equivalent in OpenCode is payload-level `service_tier = "priority"` when enabled, and `auto`/unset when disabled. For a deterministic always-on setup, setting `agent.build.options.serviceTier = "priority"` and `agent.plan.options.serviceTier = "priority"` is the simplest config-only approach. [R2][R10][R12]

## 7) Non-equivalences and constraints

- Codex docs describe ChatGPT-credit fast mode behavior and billing semantics that are product-level, not only payload-level. [W1][W2]
- OpenCode command execution path for custom commands is agent-mediated today, so a user-defined `/fast` command is not inherently an instant native command unless core command registration is extended. [R12][I2][I3]

## 8) Evidence table

| Claim | Evidence |
|---|---|
| `/fast` toggles and supports `on/off/status` | `codex-rs/tui/src/chatwidget.rs` `dispatch_command` + `dispatch_command_with_args` [R1] |
| Toggle updates future turns | `OverrideTurnContext.service_tier` in protocol + app event send [R1][R7] |
| Selection is persisted | `PersistServiceTierSelection` + `ConfigEditsBuilder::set_service_tier` [R8] |
| No dedicated fast endpoint | responses endpoint path + WS response.create flow [R3][R4] |
| Payload control field is `service_tier` | request structs in codex-api [R5] |
| Internal Fast maps to wire `priority` | `build_responses_request` mapping code [R2] |
| OpenCode supports equivalent field | OpenCode provider maps `serviceTier` -> `service_tier` [R10] |
| OpenCode can set it statically in config | `agent.options` are merged into runtime options before send [R12] |

## 9) Citations

### Repository citations

- [R1] `/tmp/research-codex-cli/codex-rs/tui/src/chatwidget.rs`: `dispatch_command` (around line 3876), `dispatch_command_with_args` (around line 4205), `set_service_tier_selection` (around line 7420).
- [R2] `/tmp/research-codex-cli/codex-rs/core/src/client.rs`: `build_responses_request` mapping `ServiceTier::Fast` -> `"priority"` (around lines 490-551).
- [R3] `/tmp/research-codex-cli/codex-rs/codex-api/src/endpoint/responses.rs`: stream request serialization and POST path `responses` (around lines 58-126).
- [R4] `/tmp/research-codex-cli/codex-rs/codex-api/src/endpoint/responses_websocket.rs`: websocket `stream_request` for `ResponsesWsRequest` (around lines 216-270).
- [R5] `/tmp/research-codex-cli/codex-rs/codex-api/src/common.rs`: `ResponsesApiRequest.service_tier`, `ResponseCreateWsRequest.service_tier`, `ResponsesWsRequest::ResponseCreate` (around lines 144-218).
- [R6] `/tmp/research-codex-cli/codex-rs/tui/src/slash_command.rs`: `/fast` command metadata and inline-args support (command description / `supports_inline_args`).
- [R7] `/tmp/research-codex-cli/codex-rs/protocol/src/protocol.rs`: `service_tier` override fields in `Op` payloads (around lines 241-307).
- [R8] `/tmp/research-codex-cli/codex-rs/tui/src/app.rs` and `/tmp/research-codex-cli/codex-rs/tui/src/app_event.rs`: `PersistServiceTierSelection` handling and persistence write.
- [R9] `/tmp/research-opencode/packages/plugin/src/index.ts`: plugin hook surface including `"chat.params"`.
- [R10] `/tmp/research-opencode/packages/opencode/src/provider/sdk/copilot/responses/openai-responses-language-model.ts`: `serviceTier` option and serialization to `service_tier`.
- [R11] `/tmp/research-codex-cli/codex-rs/core/src/config/mod.rs`: service tier config merge/selection path.
- [R12] `/tmp/research-opencode/packages/opencode/src/session/llm.ts`: `mergeDeep(input.agent.options)` merges agent options into final request options before provider send.

### Web/docs citations

- [W1] https://developers.openai.com/codex/speed
- [W2] https://developers.openai.com/codex/auth

### Issue citations

- [I1] https://github.com/openai/codex/issues/13960
- [I2] https://github.com/anomalyco/opencode/issues/10262
- [I3] https://github.com/anomalyco/opencode/issues/5305
