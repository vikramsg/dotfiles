# Bidirectional Mode Transition Reminder Plugin

## Goal

Add an auto-discovered TypeScript OpenCode plugin that injects a model-visible
`<system-reminder>` when the active primary agent changes in either direction:

- `discuss` -> `build`
- `build` -> `discuss`

The reminder must be attached to the latest user turn before model conversion,
remain present for continuation calls in that turn, and not appear on same-mode
or unrelated-agent turns.

## Design

Use `experimental.chat.messages.transform` because it receives the complete
message history at the same request stage needed for native-style reminders.
Keep the plugin stateless so it works after process restarts and when resuming an
existing session.

For each hook call:

1. Find the latest user message by scanning backward.
2. Read its active mode from `user.info.agent`.
3. Scan backward only before that user message for the nearest assistant.
4. Read the preceding mode from `assistant.info.mode`, which matches the pinned
   `@opencode-ai/plugin` 1.4.2 types.
5. Select a reminder only for an exact, case-sensitive `discuss`/`build`
   transition.
6. Find the latest non-ignored, nonblank text part on the selected user message.
7. Append two newlines and the selected reminder unless that reminder is already
   present in any usable text part on the message.
8. Return without mutation when history or usable text is missing.

Do not create a new message part because plugin-facing `Part` values require
OpenCode identifiers. Mutating existing text is model-equivalent: OpenCode
converts both ordinary and synthetic text parts into user text.

Use these reminder contracts:

```text
<system-reminder>
Your operational mode has changed from discuss to build.
You are no longer in read-only discussion mode.
You are permitted to make file changes, run shell commands, and use available tools as needed.
Continue to honor the user's decisions, active plans, project instructions, and all other current instructions.
</system-reminder>
```

```text
<system-reminder>
Your operational mode has changed from build to discuss.
Discussion mode is active. You are now in a read-only phase.
Do not make file changes or run commands that modify the system. You may only observe, analyze, discuss, and plan, except that you may write plan files under `.agents/plans/` when the user asks for a plan.
</system-reminder>
```

The transform hook also runs during compaction and provides no invocation
metadata that can distinguish compaction. Accept deterministic application of
the same history rule there; the mutation is applied to OpenCode's transformed
message set and is not persisted by this plugin.

## Files

### `opencode/plugins/mode-transition-reminder.ts`

- Import `Hooks` and `Plugin` types from `@opencode-ai/plugin`.
- Define the two reminder strings and transition selection internally.
- Derive the callback type from
  `NonNullable<Hooks["experimental.chat.messages.transform"]>`.
- Implement backward index scans instead of relying on global history searches.
- Register the callback from one default plugin export.
- Do not export helper functions or constants from the active plugin module;
  OpenCode can treat exported functions as plugin entry points.
- Do not add logging, filesystem access, or session state.

### `opencode/tests/plugins/mode-transition-reminder.test.ts`

- Use Vitest and import the plugin's default export.
- Initialize the plugin with a minimal typed `PluginInput` fixture.
- Obtain and invoke the registered `experimental.chat.messages.transform` hook.
- Build small SDK-shaped message factories, limiting type assertions to fixture
  boundaries.
- Assert exact text mutation and occurrence counts rather than snapshots.

Cover these cases:

1. `discuss` assistant followed by a `build` user appends the build reminder.
2. `build` assistant followed by a `discuss` user appends the discuss reminder.
3. The original user text is preserved before the appended reminder.
4. `build` -> `build` and `discuss` -> `discuss` do not mutate text.
5. Missing prior assistant does not inject a reminder.
6. Unsupported or differently cased agent names do not inject a reminder.
7. The nearest assistant before the latest user wins over an older opposite-mode
   assistant.
8. Assistants and tool-continuation messages after the latest user do not affect
   transition detection.
9. Calling the hook twice on the same output does not duplicate the reminder.
10. If the reminder already exists in another usable text part, it is not added
    again.
11. With multiple usable text parts, the reminder is appended to the last one.
12. Empty messages, no user message, file-only parts, ignored text, blank text,
    and an unusable latest user return safely without mutating an older turn.
13. The default plugin export registers exactly the expected transform hook.

### `opencode/commands/build.md`

- Preserve `agent: build`, `subtask: false`, and `$ARGUMENTS`.
- Remove the command-local reminder text so the plugin is the single transition
  reminder source.
- Change the description from a reminder description to a concise build-agent
  execution description.

### `opencode/tsconfig.plugins.json`

- Add a strict, no-emit TypeScript configuration for active TypeScript plugins
  and plugin tests.
- Use `NodeNext` module and module resolution, ES2022 target, Node types, and
  `allowImportingTsExtensions`.
- Include `plugins/**/*.ts` and `tests/plugins/**/*.ts` only.

### `opencode/package.json`

- Add `check:plugins` using `tsc -p tsconfig.plugins.json`.
- Add `test:plugins` using `vitest run tests/plugins`.
- Add `npm run check:plugins` to the existing `build` script.
- Do not add dependencies or change `package-lock.json`.

## Implementation Order

1. Add the plugin test file and plugin TypeScript configuration.
2. Add `check:plugins` and `test:plugins` scripts.
3. Run the targeted checks and confirm the tests fail only because the plugin is
   not implemented yet.
4. Implement the plugin and make the targeted tests pass.
5. Remove the duplicate reminder body from `/build`.
6. Run the complete automated verification.
7. Refresh the symlinked OpenCode configuration, restart OpenCode, and manually
   test both transition directions.

## Verification

Run from `opencode/`:

```bash
npm run test:plugins
npm run check:plugins
npm run build
npm run test:sandbox:v2
```

Then run from the repository root:

```bash
just opencode
```

Use the `tmux-terminal-testing` skill for manual acceptance testing. Inspect
existing tmux resources first, create a dedicated test window or session, record
its stable IDs, and clean up only the resources created for this test.

Quit and restart OpenCode inside the isolated tmux terminal so it loads the new
plugin. Send one scenario at a time and inspect the pane between scenarios.
Manually verify:

1. Start in `discuss`, produce one assistant response, then invoke `/build` with
   an implementation request. Confirm the build turn proceeds without claiming
   discussion restrictions still apply.
2. From a completed build response, switch to `discuss` or invoke a command that
   selects `discuss`. Confirm the response remains read-only and does not edit.
3. Exercise at least one tool continuation in each transition turn and confirm
   behavior does not revert mid-turn.
4. Send a second same-mode message in each mode and confirm no transition
   reminder is added.
5. Capture the pane output needed to confirm the active agent, refusal or edit
   behavior, tool continuation behavior, and return to an idle prompt.
6. Close the dedicated tmux resource and verify that pre-existing sessions and
   windows remain intact.

## Acceptance Criteria

- Both transition directions receive exactly one matching reminder per user
  turn.
- Same-mode and unrelated-agent turns receive no reminder.
- Detection uses the nearest assistant before the latest user, not any matching
  assistant in session history.
- Continuation calls for the transition turn continue to receive the reminder.
- Existing user text and unrelated message parts remain unchanged.
- The plugin does not throw on incomplete or unsupported histories.
- `/build` remains available but no longer duplicates reminder text.
- Plugin unit tests, strict type checking, the repository build, and existing
  sandbox v2 tests pass.
- Manual acceptance testing follows the `tmux-terminal-testing` skill and reports
  the tested scenarios, terminal dimensions, created tmux resource IDs, and
  cleanup confirmation.
