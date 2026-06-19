import { appendFile, mkdir, mkdtemp, readFile } from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import type { PluginInput, Hooks, Plugin } from "@opencode-ai/plugin";
import { pathToFileURL } from "node:url";

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
        const outputFile = path.join(root, options.output_file);
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

const DefaultToolCallPlugin = buildRecordToolCallPlugin({
  output_file: "tool_calls.jsonl",
  output_dir: ".agents/outputs/",
});

export default DefaultToolCallPlugin;

// FIXME: Everything after this is only for testing the plugin for now
async function runMain() {
  const worktree = await mkdtemp(
    path.join(os.tmpdir(), "persist-tool-call-run-"),
  );

  const output_dir = worktree;
  const output_file = "test_file.jsonl";

  const testToolCall = buildRecordToolCallPlugin({
    output_dir: output_dir,
    output_file: output_file,
  });

  const hooks = await testToolCall({
    client: {} as never,
    project: {} as never,
    directory: worktree,
    worktree,
    experimental_workspace: {} as never,
    serverUrl: new URL("http://localhost"),
    $: {} as never,
  });

  try {
    await hooks["tool.execute.before"]?.(
      {
        tool: "bash",
        sessionID: "ses_manual_test",
        callID: "call_manual_test",
      },
      {
        args: {
          command: "printf plugin-demo",
        },
      },
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.log(`Caught expected error: ${message}`);
  }

  const outputFile = path.join(output_dir, output_file);

  console.log(`Output file: ${outputFile}`);
  console.log(await readFile(outputFile, "utf8"));
}

const entrypoint = process.argv[1] ? pathToFileURL(process.argv[1]).href : "";

if (import.meta.url === entrypoint) {
  await runMain();
}
