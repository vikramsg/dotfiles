import { appendFile, mkdir } from "node:fs/promises";
import path from "node:path";
import type { Plugin, PluginInput, Hooks } from "@opencode-ai/plugin";

const OUTPUT_DIR = path.join(".agents", "tool-call-blocks");
const OUTPUT_FILE = "tool-calls.jsonl";

const OpenCodePluginEvents = {
  ToolExecuteBefore: "tool.execute.before",
  ToolExecuteAfter: "tool.execute.after",
} as const satisfies Record<string, keyof Hooks>;

export const PersistToolCallAndStop: Plugin = async (input: PluginInput) => {
  const { directory, worktree } = input;
  const root = directory || worktree;

  return {
    [OpenCodePluginEvents.ToolExecuteBefore]: async (input, output) => {
      const outputDir = path.join(root, OUTPUT_DIR);
      const outputFile = path.join(outputDir, OUTPUT_FILE);
      const record = {
        at: new Date().toISOString(),
        hook: OpenCodePluginEvents.ToolExecuteBefore,
        sessionID: input.sessionID,
        callID: input.callID,
        tool: input.tool,
        args: output.args,
      };

      await mkdir(outputDir, { recursive: true });
      await appendFile(outputFile, `${JSON.stringify(record)}\n`, "utf8");

      throw new Error(`Blocked tool call after persisting: ${input.tool}`);
    },
  };
};

export default PersistToolCallAndStop;
