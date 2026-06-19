import { appendFile, mkdir } from "node:fs/promises";
import path from "node:path";
import type { Plugin, PluginInput } from "@opencode-ai/plugin";

const OUTPUT_DIR = path.join(".agents", "tool-call-blocks");
const OUTPUT_FILE = "tool-calls.jsonl";

export const PersistToolCallAndStop: Plugin = async (input: PluginInput) => {
  const { directory, worktree } = input;
  const root = directory || worktree;

  return {
    "tool.execute.before": async (input, output) => {
      const outputDir = path.join(root, OUTPUT_DIR);
      const outputFile = path.join(outputDir, OUTPUT_FILE);
      const record = {
        at: new Date().toISOString(),
        hook: "tool.execute.before",
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
