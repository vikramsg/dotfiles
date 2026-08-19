import { Message } from "@opencode-ai/ai";
import { beforeEach, describe, expect, it, vi } from "vitest";

import modeTransitionReminder, {
  BUILD_REMINDER,
  DISCUSS_REMINDER,
  selectReminder,
} from "../../plugins/mode-transition-reminder-v2.ts";

type ContextEvent = {
  sessionID: string;
  agent: string;
  model: string;
  system: never[];
  messages: Message[];
  tools: Record<string, never>;
};

type ContextHandler = (event: ContextEvent) => Promise<void> | void;

function user(id: string, text = "Continue"): Message {
  return Message.make({ id, role: "user", content: text });
}

function assistant(id: string, text = "Done"): Message {
  return Message.make({ id, role: "assistant", content: text });
}

function event(
  agent: string,
  userID: string,
  options: { sessionID?: string; messages?: Message[] } = {},
): ContextEvent {
  return {
    sessionID: options.sessionID ?? "session-1",
    agent,
    model: "test/model",
    system: [],
    messages: options.messages ?? [user(userID)],
    tools: {},
  };
}

function text(message: Message): string {
  return message.content
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("\n");
}

function latestUserText(input: ContextEvent): string {
  const latest = input.messages.findLast((message) => message.role === "user");
  if (!latest) throw new Error("Missing user message");
  return text(latest);
}

async function harness() {
  let handler: ContextHandler | undefined;
  const dispose = vi.fn(async () => undefined);
  const hook = vi.fn(
    async (name: string, callback: ContextHandler) => {
      if (name !== "context") throw new Error(`Unexpected hook: ${name}`);
      handler = callback;
      return { dispose };
    },
  );
  const cleanup = await modeTransitionReminder.setup({
    session: { hook },
  } as never);

  if (!handler) throw new Error("Context hook was not registered");
  if (!cleanup) throw new Error("Cleanup was not returned");
  return { cleanup, dispose, handler, hook };
}

describe("mode transition reminder V2 plugin", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("exports the expected V2 plugin definition", () => {
    expect(modeTransitionReminder.id).toBe(
      "dotfiles.mode-transition-reminder-v2",
    );
    expect(modeTransitionReminder.setup).toBeTypeOf("function");
  });

  it.each([
    ["discuss", "build", BUILD_REMINDER],
    ["build", "discuss", DISCUSS_REMINDER],
    ["build", "build", undefined],
    ["discuss", "discuss", undefined],
    ["review", "build", undefined],
    ["Discuss", "build", undefined],
    ["discuss", "Build", undefined],
  ])(
    "selects the reminder for %s to %s",
    (previous, current, expected) => {
      expect(selectReminder(previous, current)).toBe(expected);
    },
  );

  it("does not inject on the first observed turn", async () => {
    const { handler } = await harness();
    const input = event("discuss", "user-1");

    await handler(input);

    expect(latestUserText(input)).toBe("Continue");
  });

  it("injects exact reminders on both transition edges", async () => {
    const { handler } = await harness();
    await handler(event("discuss", "user-1"));

    const build = event("build", "user-2");
    await handler(build);
    expect(latestUserText(build)).toBe(`Continue\n${BUILD_REMINDER}`);

    const discuss = event("discuss", "user-3");
    await handler(discuss);
    expect(latestUserText(discuss)).toBe(`Continue\n${DISCUSS_REMINDER}`);
  });

  it("injects on each fresh projection for one transitioning user turn", async () => {
    const { handler } = await harness();
    await handler(event("discuss", "user-1"));

    const firstPass = event("build", "user-2");
    await handler(firstPass);
    expect(latestUserText(firstPass)).toContain(BUILD_REMINDER);

    const toolContinuation = event("build", "user-2", {
      messages: [
        user("user-2"),
        assistant("assistant-2", "Called a tool"),
      ],
    });
    await handler(toolContinuation);
    expect(latestUserText(toolContinuation)).toContain(BUILD_REMINDER);
  });

  it("does not duplicate a reminder in one request projection", async () => {
    const { handler } = await harness();
    await handler(event("discuss", "user-1"));
    const input = event("build", "user-2");

    await handler(input);
    await handler(input);

    expect(latestUserText(input).split(BUILD_REMINDER)).toHaveLength(2);
  });

  it("forgets a transition when the next user message arrives", async () => {
    const { handler } = await harness();
    await handler(event("discuss", "user-1"));
    await handler(event("build", "user-2"));
    const followUp = event("build", "user-3");

    await handler(followUp);

    expect(latestUserText(followUp)).toBe("Continue");
  });

  it("handles repeated mode changes and same-mode replies", async () => {
    const { handler } = await harness();
    const sequence = [
      ["discuss", "user-1", undefined],
      ["build", "user-2", BUILD_REMINDER],
      ["build", "user-3", undefined],
      ["discuss", "user-4", DISCUSS_REMINDER],
      ["discuss", "user-5", undefined],
      ["build", "user-6", BUILD_REMINDER],
    ] as const;

    for (const [agent, userID, reminder] of sequence) {
      const input = event(agent, userID);
      await handler(input);
      if (reminder) expect(latestUserText(input)).toContain(reminder);
      else expect(latestUserText(input)).toBe("Continue");
    }
  });

  it("keeps transition state independent between sessions", async () => {
    const { handler } = await harness();
    await handler(event("discuss", "a-1", { sessionID: "session-a" }));
    await handler(event("build", "b-1", { sessionID: "session-b" }));

    const sessionA = event("build", "a-2", { sessionID: "session-a" });
    const sessionB = event("discuss", "b-2", { sessionID: "session-b" });
    await handler(sessionA);
    await handler(sessionB);

    expect(latestUserText(sessionA)).toContain(BUILD_REMINDER);
    expect(latestUserText(sessionB)).toContain(DISCUSS_REMINDER);
  });

  it("changes only the latest user message in the request projection", async () => {
    const { handler } = await harness();
    await handler(event("discuss", "user-1"));
    const older = user("user-old", "Older request");
    const input = event("build", "user-2", {
      messages: [older, assistant("assistant-1"), user("user-2", "Latest")],
    });

    await handler(input);

    expect(text(input.messages[0]!)).toBe("Older request");
    expect(latestUserText(input)).toBe(`Latest\n${BUILD_REMINDER}`);
  });

  it("does not mutate the stored message fixture", async () => {
    const { handler } = await harness();
    await handler(event("discuss", "user-1"));
    const stored = [user("user-2", "Stored request")];
    const projection = stored.slice();
    const input = event("build", "user-2", { messages: projection });

    await handler(input);

    expect(text(stored[0]!)).toBe("Stored request");
    expect(latestUserText(input)).toContain(BUILD_REMINDER);
  });

  it("disposes the hook and clears ephemeral state", async () => {
    const { cleanup, dispose, handler, hook } = await harness();
    await handler(event("discuss", "user-1"));

    await cleanup();

    expect(hook).toHaveBeenCalledOnce();
    expect(dispose).toHaveBeenCalledOnce();
    const afterCleanup = event("build", "user-2");
    await handler(afterCleanup);
    expect(latestUserText(afterCleanup)).toBe("Continue");
  });
});
