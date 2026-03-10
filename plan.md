# Plan: deterministic fast-mode control without OpenCode core changes

## 1) Goal

Implement deterministic fast-mode control that does not rely on model-executed markdown slash commands and does not require OpenCode core changes.

The implementation must:

- Toggle/read state through a deterministic local controller command.
- Apply outbound OpenAI request tier mutation through plugin `chat.params`.
- Be usable from inside TUI via shell mode (`!`), and outside TUI non-interactively.
- Provide a deterministic status output surface.

## 2) Scope and non-scope

### In scope

- Add deterministic controller command `oc-fast` with `on|off|status|toggle`.
- Persist state in `.opencode/fast-mode.json`.
- Update plugin to read persisted state and set OpenAI `serviceTier` deterministically in `chat.params`.
- Ensure TUI interaction path uses shell mode (`!`) so command execution is deterministic.
- Add deterministic verification evidence path (`.opencode/fast-mode.audit.log`).

### Out of scope

- Reproducing ChatGPT plan billing semantics.
- Modifying upstream OpenAI provider capabilities.
- Implementing OpenCode core native slash command registration.
- Using markdown slash command execution as source of truth for fast mode.

## 3) Approach

### Deterministic architecture

Use an external state controller + plugin request mutation:

1. Add `opencode/plugins/fast-mode/oc-fast` script.
2. Script writes/reads global state at `~/.local/share/opencode/plugins/fast-mode.json` (or `$XDG_DATA_HOME/opencode/plugins/fast-mode.json`).
3. Plugin `opencode/plugins/fast-mode/index.ts` reads state and sets `output.options.serviceTier` in `chat.params`.
4. Plugin writes audit entries only when `OPENCODE_FAST_MODE_AUDIT` is enabled.
5. Use from TUI via shell mode: `!oc-fast on|off|status`.

Why deterministic:

- State toggling is local file I/O.
- Runtime request mutation is plugin hook logic, not model interpretation.
- TUI interaction uses shell execution path, not markdown command prompt path.

Tradeoff:

- No native `/fast` slash command entry; deterministic control is via shell command.

## 4) Delivery sequence

### Phase 1

1. Update `plan.md` and remove non-deterministic path from primary design.
2. Implement `oc-fast` command.
3. Update plugin to state-file-driven `chat.params` mutation + audit logging.
4. Remove markdown `/fast` command to prevent accidental non-deterministic use.
5. Document TUI shell-mode usage.

### Phase 2

1. Run verification matrix and record outputs.
2. Confirm acceptance criteria.

## 5) Detailed task breakdown

### Task group A: deterministic controller

- Add `oc-fast` executable script.
- Implement commands `on|off|status|toggle`.
- Resolve state file location to project root and persist atomically.

Acceptance criteria:
- `oc-fast on|off|status|toggle` behaves deterministically with exit code 0.
- `~/.local/share/opencode/plugins/fast-mode.json` persists across sessions.

### Task group B: plugin request mutation

- Remove tool-based toggling from plugin.
- In `chat.params`, read state and apply OpenAI-only `serviceTier`.
- Append audit entries only when `OPENCODE_FAST_MODE_AUDIT` is enabled.

Acceptance criteria:
- Enabled mode sets tier to `priority` on requests.
- Disabled mode resets to `auto` (or equivalent default behavior).
- Non-OpenAI providers are untouched.

### Task group C: TUI interaction path

- Use shell mode (`!`) in TUI to run `oc-fast ...`.
- Add docs/examples for this path.

Acceptance criteria:
- From TUI shell mode, `oc-fast status` returns deterministic state text.

### Task group D: Verification and hardening

- Run deterministic CLI checks with `oc-fast on|off|status|toggle`.
- Run TUI shell-mode path checks (`!oc-fast ...`).
- Run at least one prompt call and verify `fast-mode.audit.log` entry contains expected tier.
- Verify non-OpenAI guard path in audit/log behavior.

Acceptance criteria:
- Audit log confirms applied tier for OpenAI requests.
- All deterministic command tests pass.

## 6) Validation matrix

| Scenario | Expected |
|---|---|
| `oc-fast on` | writes enabled state deterministically |
| `oc-fast off` | writes disabled state deterministically |
| `oc-fast status` | prints persisted state deterministically |
| `oc-fast toggle` | flips persisted state deterministically |
| restart OpenCode | prior state restored from global state file |
| prompt with OpenAI provider | audit shows `serviceTier=priority` when enabled (with env var enabled) |
| prompt with OpenAI provider disabled | audit shows `serviceTier=auto` when disabled (with env var enabled) |
| non-OpenAI provider prompt | no forced OpenAI `serviceTier` mutation |
| TUI shell mode | `!oc-fast status` works from within prompt UI |

## 7) Risks and mitigations

- **Risk:** provider does not honor priority tier.
  - **Mitigation:** provider guard + clear fallback messaging.
- **Risk:** state drift between sessions.
  - **Mitigation:** single source of truth persistence path.
- **Risk:** agent-mediated command latency in Option A.
  - **Mitigation:** roadmap Option B for instant command execution.

## 8) Rollback strategy

- Disable plugin file to immediately stop behavior.
- Remove `oc-fast` script or stop using it.
- Clear persisted fast-mode state file.

## 9) Deliverables

- `opencode/codex.md` (findings/evidence doc)
- Plugin implementation files
- `oc-fast` deterministic controller script
- Operator notes for verification and rollback

## 10) Done definition

- `oc-fast on|off|status|toggle` works end-to-end.
- Request tier mutation is observable and correct.
- Behavior is safe on unsupported providers.
- Documentation includes usage, caveats, and rollback steps.
- Deterministic `oc-fast` controls pass from shell and TUI shell mode.
- Audit verification demonstrates request-tier mutation behavior.
