import { Message } from "@opencode-ai/ai";
import { Plugin } from "@opencode-ai/plugin";

export const BUILD_REMINDER = `<system-reminder>
Your operational mode has changed from discuss to build.
You are no longer in read-only discussion mode.
You are permitted to make file changes, run shell commands, and use available tools as needed.
Continue to honor the user's decisions, active plans, project instructions, and all other current instructions.
</system-reminder>`;

export const DISCUSS_REMINDER = `<system-reminder>
Your operational mode has changed from build to discuss.
Discussion mode is active. You are now in a read-only phase.
Do not make file changes or run commands that modify the system. You may only observe, analyze, discuss, and plan, except that you may write plan files under \`.agents/plans/\` when the user asks for a plan.
</system-reminder>`;

type Mode = "build" | "discuss";

type Transition = {
  userMessageID: string;
  reminder: string;
};

type SessionTransition = {
  previousAgent: string;
  latestUserMessageID: string;
  transition?: Transition;
};

export function selectReminder(
  previousAgent: string,
  currentAgent: string,
): string | undefined {
  if (previousAgent === "discuss" && currentAgent === "build") {
    return BUILD_REMINDER;
  }
  if (previousAgent === "build" && currentAgent === "discuss") {
    return DISCUSS_REMINDER;
  }
  return undefined;
}

function containsReminder(message: Message, reminder: string): boolean {
  return message.content.some(
    (part) => part.type === "text" && part.text.includes(reminder),
  );
}

export default Plugin.define({
  id: "dotfiles.mode-transition-reminder-v2",

  async setup(ctx) {
    const sessions = new Map<string, SessionTransition>();

    const registration = await ctx.session.hook("context", (event) => {
      let userIndex = -1;
      for (let index = event.messages.length - 1; index >= 0; index -= 1) {
        if (event.messages[index]?.role === "user") {
          userIndex = index;
          break;
        }
      }

      if (userIndex < 0) return;
      const userMessage = event.messages[userIndex];
      if (!userMessage?.id) return;

      const sessionID = String(event.sessionID);
      const currentAgent = String(event.agent);
      const state = sessions.get(sessionID);

      if (!state) {
        sessions.set(sessionID, {
          previousAgent: currentAgent,
          latestUserMessageID: userMessage.id,
        });
        return;
      }

      if (state.latestUserMessageID !== userMessage.id) {
        const reminder = selectReminder(state.previousAgent, currentAgent);
        state.previousAgent = currentAgent;
        state.latestUserMessageID = userMessage.id;
        state.transition = reminder
          ? { userMessageID: userMessage.id, reminder }
          : undefined;
      }

      const transition = state.transition;
      if (
        !transition ||
        transition.userMessageID !== userMessage.id ||
        containsReminder(userMessage, transition.reminder)
      ) {
        return;
      }

      event.messages[userIndex] = Message.make({
        ...userMessage,
        content: [...userMessage.content, Message.text(transition.reminder)],
      });
    });

    return async () => {
      sessions.clear();
      await registration.dispose();
    };
  },
});
