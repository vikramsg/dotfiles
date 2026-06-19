import { appendFile, mkdir } from "node:fs/promises";
import path from "node:path";
import type { PluginInput, Hooks, Plugin } from "@opencode-ai/plugin";

interface ToolCallMetadata {
  output_dir: string;
  output_file: string;
}

const OpenCodePluginEvents = {
  ToolExecuteBefore: "tool.execute.before",
  ToolExecuteAfter: "tool.execute.after",
} as const satisfies Record<string, keyof Hooks>;

const buildRecordToolCallPlugin =
  (options: ToolCallMetadata): Plugin =>
  async (input: PluginInput): Promise<Hooks> => {
    const { directory, worktree } = input;
    const root = directory || worktree;

    return {
      [OpenCodePluginEvents.ToolExecuteBefore]: async (input, output) => {
        const outputDir = path.join(root, options.output_dir);
        const outputFile = path.join(outputDir, options.output_file);
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

const DefaultRecordToolCallPlugin = buildRecordToolCallPlugin({
  output_file: "tool_calls.jsonl",
  output_dir: ".agents/outputs/",
});

export default DefaultRecordToolCallPlugin;
