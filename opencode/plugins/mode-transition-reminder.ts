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
