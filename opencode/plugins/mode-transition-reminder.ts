/*
Use `experimental.chat.messages.transform` to

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

`experimental.chat.messages.transform` receives the complete
message history at the same request stage needed for native-style reminders.

Use these reminder contracts:

```text
<system-reminder>
...
</system-reminder>
```

```text
<system-reminder>
...
</system-reminder>
```
*/

import type { Hooks, Plugin } from "@opencode-ai/plugin";

const BUILD_REMINDER = `<system-reminder>
Your operational mode has changed from discuss to build.
You are no longer in read-only discussion mode.
You are permitted to make file changes, run shell commands, and use available tools as needed.
Continue to honor the user's decisions, active plans, project instructions, and all other current instructions.
</system-reminder>`;

const DISCUSS_REMINDER = `<system-reminder>
Your operational mode has changed from build to discuss.
Discussion mode is active. You are now in a read-only phase.
Do not make file changes or run commands that modify the system. You may only observe, analyze, discuss, and plan, except that you may write plan files under \`.agents/plans/\` when the user asks for a plan.
</system-reminder>`;

type Transform = NonNullable<
  Hooks["experimental.chat.messages.transform"]
>;

// Match OpenCode's default transition behavior: mutate request-local history
// for each model pass without persisting the reminder to the session database.
const transform: Transform = async (_input, output) => {
  let userIndex = -1;

  for (let index = output.messages.length - 1; index >= 0; index -= 1) {
    if (output.messages[index]?.info.role === "user") {
      userIndex = index;
      break;
    }
  }

  if (userIndex < 0) return;

  const userMessage = output.messages[userIndex];
  if (!userMessage || userMessage.info.role !== "user") return;

  let previousMode: string | undefined;
  for (let index = userIndex - 1; index >= 0; index -= 1) {
    const message = output.messages[index];
    if (message?.info.role === "assistant") {
      previousMode = message.info.mode;
      break;
    }
  }

  const reminder =
    previousMode === "discuss" && userMessage.info.agent === "build"
      ? BUILD_REMINDER
      : previousMode === "build" && userMessage.info.agent === "discuss"
        ? DISCUSS_REMINDER
        : undefined;

  if (!reminder) return;

  let target: (typeof userMessage.parts)[number] | undefined;
  for (let index = userMessage.parts.length - 1; index >= 0; index -= 1) {
    const part = userMessage.parts[index];
    if (
      part?.type !== "text" ||
      part.ignored === true ||
      part.text.trim().length === 0
    ) {
      continue;
    }

    if (part.text.includes(reminder)) return;
    if (!target) target = part;
  }

  if (!target || target.type !== "text") return;
  target.text += `\n\n${reminder}`;
};

export default (async (_input) => ({
  "experimental.chat.messages.transform": transform,
})) satisfies Plugin;
