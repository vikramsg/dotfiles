# Codex CLI `/fast` -> API behavior and OpenCode mapping

## 1) Purpose and scope

This document captures how Codex CLI `/fast` works at the API payload level, and how to replicate equivalent behavior in OpenCode without guessing. It focuses on implementation evidence from source and docs, not roadmap decisions. [R1][R2][R3][R4][W1][W2]

## 2) Executive summary

- `/fast` is a built-in Codex slash command handled in the TUI command dispatcher, including `on|off|status` argument handling. [R1]
- `/fast` does **not** use a dedicated endpoint; Codex keeps using the standard Responses API path (`responses`) and the Responses WebSocket `response.create` flow. [R3][R4][R5]
- The effective API control is a request payload field: `service_tier`. [R5]
- Internal Codex `ServiceTier::Fast` is mapped to wire value `"priority"` in request construction. [R2]
- OpenCode already exposes equivalent payload control, and for `@ai-sdk/openai` / `@ai-sdk/azure` models it can be driven either by plugin hooks or by static per-agent config. OpenCode merges agent options into runtime options, namespaces them under the `openai` provider key, and the upstream AI SDK Responses client serializes `serviceTier` to `service_tier`. [R10][R12][R13]

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
- For `@ai-sdk/openai` and `@ai-sdk/azure`, OpenCode routes provider options under the `openai` namespace and selects `sdk.responses(modelID)` for normal Responses API calls. [R10][R11]
- The upstream AI SDK OpenAI Responses client serializes `serviceTier` to request `service_tier` and strips unsupported tiers when necessary. [R13]

Therefore, Codex `/fast` equivalent in OpenCode is payload-level `service_tier = "priority"` when enabled, and `auto`/unset when disabled. For a deterministic always-on setup, setting `agent.build.options.serviceTier = "priority"` and `agent.plan.options.serviceTier = "priority"` is the simplest config-only approach. [R2][R10][R12][R13]

## 7) Non-equivalences and constraints

- Codex docs describe ChatGPT-credit fast mode behavior and billing semantics that are product-level, not only payload-level. [W1][W2]
- OpenCode command execution path for custom commands is agent-mediated today, so a user-defined `/fast` command is not inherently an instant native command unless core command registration is extended. [R14][I2][I3]

## 8) Evidence table

| Claim | Evidence |
|---|---|
| `/fast` toggles and supports `on/off/status` | `codex-rs/tui/src/chatwidget.rs` `dispatch_command` + `dispatch_command_with_args` [R1] |
| Toggle updates future turns | `OverrideTurnContext.service_tier` in protocol + app event send [R1][R7] |
| Selection is persisted | `PersistServiceTierSelection` + `ConfigEditsBuilder::set_service_tier` [R8] |
| No dedicated fast endpoint | responses endpoint path + WS response.create flow [R3][R4] |
| Payload control field is `service_tier` | request structs in codex-api [R5] |
| Internal Fast maps to wire `priority` | `build_responses_request` mapping code [R2] |
| OpenCode can set it statically in config | `agent.options` are merged into runtime options before send [R12] |
| OpenCode routes OpenAI/Azure options to Responses client | provider key mapping + `sdk.responses(modelID)` selection [R10][R11] |
| OpenAI Responses client emits `service_tier` | upstream AI SDK serializes `serviceTier` and strips unsupported tiers [R13] |

## 9) Citations

### Repository citations

- [R1] https://github.com/openai/codex/blob/2bc3e52a91bb88a0e067a95f8f8559f8711d30e6/codex-rs/tui/src/chatwidget.rs#L3876 and https://github.com/openai/codex/blob/2bc3e52a91bb88a0e067a95f8f8559f8711d30e6/codex-rs/tui/src/chatwidget.rs#L4205 and https://github.com/openai/codex/blob/2bc3e52a91bb88a0e067a95f8f8559f8711d30e6/codex-rs/tui/src/chatwidget.rs#L7420 — `/fast` toggle logic, `on|off|status` handling, and service-tier setter.
- [R2] https://github.com/openai/codex/blob/2bc3e52a91bb88a0e067a95f8f8559f8711d30e6/codex-rs/core/src/client.rs#L490-L551 — `build_responses_request` maps `ServiceTier::Fast` to wire payload `"priority"`.
- [R3] https://github.com/openai/codex/blob/2bc3e52a91bb88a0e067a95f8f8559f8711d30e6/codex-rs/codex-api/src/endpoint/responses.rs#L58-L126 — Responses HTTP/SSE request serialization and `responses` POST path.
- [R4] https://github.com/openai/codex/blob/2bc3e52a91bb88a0e067a95f8f8559f8711d30e6/codex-rs/codex-api/src/endpoint/responses_websocket.rs#L216-L270 — websocket `stream_request` for `ResponsesWsRequest`.
- [R5] https://github.com/openai/codex/blob/2bc3e52a91bb88a0e067a95f8f8559f8711d30e6/codex-rs/codex-api/src/common.rs#L144-L218 — `ResponsesApiRequest.service_tier`, `ResponseCreateWsRequest.service_tier`, and `ResponsesWsRequest::ResponseCreate`.
- [R6] https://github.com/openai/codex/blob/2bc3e52a91bb88a0e067a95f8f8559f8711d30e6/codex-rs/tui/src/slash_command.rs#L65-L149 — `/fast` command description, inline-arg support, and availability metadata.
- [R7] https://github.com/openai/codex/blob/2bc3e52a91bb88a0e067a95f8f8559f8711d30e6/codex-rs/protocol/src/protocol.rs#L241-L307 — per-turn and persistent `service_tier` override fields.
- [R8] https://github.com/openai/codex/blob/2bc3e52a91bb88a0e067a95f8f8559f8711d30e6/codex-rs/tui/src/app.rs#L2848-L2879 — `PersistServiceTierSelection` handling and user-facing persistence messages.
- [R9] https://github.com/sst/opencode/blob/c71d1bde5e8dcc8be49c15697ad2e5d0f2607e5e/packages/plugin/src/index.ts#L166-L177 — plugin hook surface including `"chat.params"`.
- [R10] https://github.com/sst/opencode/blob/c71d1bde5e8dcc8be49c15697ad2e5d0f2607e5e/packages/opencode/src/provider/transform.ts#L23-L31 and https://github.com/sst/opencode/blob/c71d1bde5e8dcc8be49c15697ad2e5d0f2607e5e/packages/opencode/src/provider/transform.ts#L840-L872 — `@ai-sdk/openai` / `@ai-sdk/azure` options are namespaced under `openai` for providerOptions.
- [R11] https://github.com/sst/opencode/blob/c71d1bde5e8dcc8be49c15697ad2e5d0f2607e5e/packages/opencode/src/provider/provider.ts#L88-L110 and https://github.com/sst/opencode/blob/c71d1bde5e8dcc8be49c15697ad2e5d0f2607e5e/packages/opencode/src/provider/provider.ts#L154-L205 — OpenCode uses bundled `@ai-sdk/openai` / `@ai-sdk/azure` providers and selects `sdk.responses(modelID)` for OpenAI/Azure Responses API calls.
- [R12] https://github.com/sst/opencode/blob/c71d1bde5e8dcc8be49c15697ad2e5d0f2607e5e/packages/opencode/src/session/llm.ts#L95-L131 — `mergeDeep(input.agent.options)` merges agent options into final request options before provider send.
- [R13] https://github.com/vercel/ai/blob/37b1b9d0247d498f019de0200134511647add4d9/packages/openai/src/responses/openai-responses-language-model.ts#L324-L429 — upstream `@ai-sdk/openai` Responses client serializes `serviceTier` to `service_tier` and removes unsupported tiers.
- [R14] https://github.com/sst/opencode/blob/c71d1bde5e8dcc8be49c15697ad2e5d0f2607e5e/packages/opencode/src/session/prompt.ts#L1794-L1873 — custom command execution resolves the markdown command and then calls `prompt(...)`, making it agent-mediated.

### Web/docs citations

- [W1] https://developers.openai.com/codex/speed
- [W2] https://developers.openai.com/codex/auth

### Issue citations

- [I1] https://github.com/openai/codex/issues/13960
- [I2] https://github.com/anomalyco/opencode/issues/10262
- [I3] https://github.com/anomalyco/opencode/issues/5305
