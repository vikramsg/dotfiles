import type {
  AssistantMessage,
  FilePart,
  Part,
  TextPart,
  ToolPart,
  UserMessage,
} from "@opencode-ai/sdk";
import type { Hooks, PluginInput } from "@opencode-ai/plugin";
import { beforeEach, describe, expect, it } from "vitest";

import modeTransitionReminder from "../../plugins/mode-transition-reminder.ts";

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
type TransformOutput = Parameters<Transform>[1];
type MessageWithParts = TransformOutput["messages"][number];

let nextID = 0;

function id(prefix: string): string {
  nextID += 1;
  return `${prefix}-${nextID}`;
}

function textPart(text: string, options: { ignored?: boolean } = {}): TextPart {
  return {
    id: id("part"),
    sessionID: "session-1",
    messageID: "message-1",
    type: "text",
    text,
    ...options,
  };
}

function filePart(): FilePart {
  return {
    id: id("part"),
    sessionID: "session-1",
    messageID: "message-1",
    type: "file",
    mime: "text/plain",
    url: "file:///tmp/request.txt",
  };
}

function toolPart(): ToolPart {
  return {
    id: id("part"),
    sessionID: "session-1",
    messageID: "message-1",
    type: "tool",
    callID: id("call"),
    tool: "read",
    state: {
      status: "completed",
      input: {},
      output: "contents",
      title: "Read",
      metadata: {},
      time: { start: 1, end: 2 },
    },
  };
}

function userMessage(
  agent: string,
  parts: Part[] = [textPart("Implement the change")],
): MessageWithParts {
  const info: UserMessage = {
    id: id("user"),
    sessionID: "session-1",
    role: "user",
    time: { created: 1 },
    agent,
    model: { providerID: "test", modelID: "test" },
  };

  return { info, parts };
}

function assistantMessage(
  mode: string,
  parts: Part[] = [],
): MessageWithParts {
  const info: AssistantMessage = {
    id: id("assistant"),
    sessionID: "session-1",
    role: "assistant",
    time: { created: 1, completed: 2 },
    parentID: "user-0",
    modelID: "test",
    providerID: "test",
    mode,
    path: { cwd: "/tmp", root: "/tmp" },
    cost: 0,
    tokens: {
      input: 0,
      output: 0,
      reasoning: 0,
      cache: { read: 0, write: 0 },
    },
  };

  return { info, parts };
}

function countOccurrences(text: string, value: string): number {
  return text.split(value).length - 1;
}

describe("mode transition reminder plugin", () => {
  let transform: Transform;

  beforeEach(async () => {
    nextID = 0;
    const input = {} as PluginInput;
    const hooks = await modeTransitionReminder(input);
    const registered = hooks["experimental.chat.messages.transform"];
    if (!registered) throw new Error("transform hook was not registered");
    transform = registered;
  });

  it("appends the build reminder for discuss to build", async () => {
    const text = textPart("Implement the approved plan");
    const output = {
      messages: [assistantMessage("discuss"), userMessage("build", [text])],
    };

    await transform({}, output);

    expect(text.text).toBe(`Implement the approved plan\n\n${BUILD_REMINDER}`);
    expect(text.text.startsWith("Implement the approved plan\n\n")).toBe(true);
  });

  it("appends the discuss reminder for build to discuss", async () => {
    const text = textPart("Review what changed");
    const output = {
      messages: [assistantMessage("build"), userMessage("discuss", [text])],
    };

    await transform({}, output);

    expect(text.text).toBe(`Review what changed\n\n${DISCUSS_REMINDER}`);
  });

  it.each([
    ["build", "build"],
    ["discuss", "discuss"],
  ])("does not mutate a %s to %s turn", async (previous, current) => {
    const text = textPart("Continue");
    const output = {
      messages: [assistantMessage(previous), userMessage(current, [text])],
    };

    await transform({}, output);

    expect(text.text).toBe("Continue");
  });

  it("does not inject without a prior assistant", async () => {
    const text = textPart("Implement");
    const output = { messages: [userMessage("build", [text])] };

    await transform({}, output);

    expect(text.text).toBe("Implement");
  });

  it.each([
    ["discuss", "Build"],
    ["Discuss", "build"],
    ["review", "build"],
    ["build", "general"],
  ])(
    "does not inject for unsupported transition %s to %s",
    async (previous, current) => {
      const text = textPart("Continue");
      const output = {
        messages: [assistantMessage(previous), userMessage(current, [text])],
      };

      await transform({}, output);

      expect(text.text).toBe("Continue");
    },
  );

  it("uses the nearest assistant before the latest user", async () => {
    const text = textPart("Continue building");
    const output = {
      messages: [
        assistantMessage("discuss"),
        assistantMessage("build"),
        userMessage("build", [text]),
      ],
    };

    await transform({}, output);

    expect(text.text).toBe("Continue building");
  });

  it("ignores assistants and tool continuations after the latest user", async () => {
    const text = textPart("Implement");
    const output = {
      messages: [
        assistantMessage("discuss"),
        userMessage("build", [text]),
        assistantMessage("build"),
        assistantMessage("discuss", [toolPart()]),
      ],
    };

    await transform({}, output);

    expect(text.text).toBe(`Implement\n\n${BUILD_REMINDER}`);
  });

  it("does not duplicate a reminder when called twice", async () => {
    const text = textPart("Implement");
    const output = {
      messages: [assistantMessage("discuss"), userMessage("build", [text])],
    };

    await transform({}, output);
    await transform({}, output);

    expect(countOccurrences(text.text, BUILD_REMINDER)).toBe(1);
  });

  it("does not append when another usable text part has the reminder", async () => {
    const existing = textPart(`Context\n\n${BUILD_REMINDER}`);
    const latest = textPart("Implement");
    const output = {
      messages: [
        assistantMessage("discuss"),
        userMessage("build", [existing, latest]),
      ],
    };

    await transform({}, output);

    expect(existing.text).toBe(`Context\n\n${BUILD_REMINDER}`);
    expect(latest.text).toBe("Implement");
    expect(countOccurrences(existing.text + latest.text, BUILD_REMINDER)).toBe(1);
  });

  it("appends to the last usable text part", async () => {
    const first = textPart("First");
    const ignored = textPart("Ignored", { ignored: true });
    const blank = textPart("  \n");
    const last = textPart("Last");
    const output = {
      messages: [
        assistantMessage("discuss"),
        userMessage("build", [first, ignored, blank, last]),
      ],
    };

    await transform({}, output);

    expect(first.text).toBe("First");
    expect(ignored.text).toBe("Ignored");
    expect(blank.text).toBe("  \n");
    expect(last.text).toBe(`Last\n\n${BUILD_REMINDER}`);
  });

  it.each([
    ["empty history", { messages: [] }],
    ["no user message", { messages: [assistantMessage("discuss")] }],
    [
      "file-only parts",
      {
        messages: [
          assistantMessage("discuss"),
          userMessage("build", [filePart()]),
        ],
      },
    ],
    [
      "ignored text",
      {
        messages: [
          assistantMessage("discuss"),
          userMessage("build", [textPart("Ignore", { ignored: true })]),
        ],
      },
    ],
    [
      "blank text",
      {
        messages: [
          assistantMessage("discuss"),
          userMessage("build", [textPart(" \n\t")]),
        ],
      },
    ],
  ])("returns safely for %s", async (_name, output) => {
    const before = structuredClone(output);

    await transform({}, output);

    expect(output).toEqual(before);
  });

  it("does not mutate an older turn when the latest user is unusable", async () => {
    const older = textPart("Older request");
    const output = {
      messages: [
        assistantMessage("discuss"),
        userMessage("build", [older]),
        assistantMessage("build"),
        userMessage("discuss", [filePart(), textPart(" ")]),
      ],
    };

    await transform({}, output);

    expect(older.text).toBe("Older request");
  });

  it("registers only the expected transform hook", async () => {
    const input = {} as PluginInput;
    const hooks = await modeTransitionReminder(input);

    expect(Object.keys(hooks)).toEqual([
      "experimental.chat.messages.transform",
    ]);
  });
});
