import { mkdtemp, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import DefaultRecordToolCallPlugin from "./persist-tool-call-and-stop.ts";

async function tempWorktree(): Promise<string> {
  return mkdtemp(path.join(os.tmpdir(), "persist-tool-call-test-"));
}

function pluginContext(worktree: string) {
  return {
    client: {} as never,
    project: {} as never,
    directory: worktree,
    worktree,
    experimental_workspace: {} as never,
    serverUrl: new URL("http://localhost"),
    $: {} as never,
  };
}

async function readRecords(worktree: string): Promise<unknown[]> {
  const text = await readFile(
    path.join(
      worktree,
      DefaultRecordToolCallPlugin.metadata.output_dir,
      DefaultRecordToolCallPlugin.metadata.output_file,
    ),
    "utf8",
  );

  return text
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

describe("PersistToolCallAndStop", () => {
  it("persists tool call args before blocking execution", async () => {
    const worktree = await tempWorktree();
    const hooks = await DefaultRecordToolCallPlugin(pluginContext(worktree));

    await expect(
      hooks["tool.execute.before"]?.(
        {
          tool: "bash",
          sessionID: "ses_test",
          callID: "call_test",
        },
        {
          args: { command: "printf plugin-demo" },
        },
      ),
    ).rejects.toThrow("Blocked tool call after persisting: bash");

    const [record] = await readRecords(worktree);

    expect(record).toMatchObject({
      hook: "tool.execute.before",
      sessionID: "ses_test",
      callID: "call_test",
      tool: "bash",
      args: { command: "printf plugin-demo" },
    });
    expect(typeof (record as { at?: unknown }).at).toBe("string");
  });

  it("appends records for repeated blocked tool calls", async () => {
    const worktree = await tempWorktree();
    const hooks = await DefaultRecordToolCallPlugin(pluginContext(worktree));
    const beforeTool = hooks["tool.execute.before"];

    if (!beforeTool) throw new Error("tool.execute.before hook missing");

    await expect(
      beforeTool(
        { tool: "read", sessionID: "ses_test", callID: "call_1" },
        { args: { filePath: "README.md" } },
      ),
    ).rejects.toThrow("Blocked tool call after persisting: read");
    await expect(
      beforeTool(
        { tool: "bash", sessionID: "ses_test", callID: "call_2" },
        { args: { command: "pwd" } },
      ),
    ).rejects.toThrow("Blocked tool call after persisting: bash");

    const records = await readRecords(worktree);

    expect(records).toHaveLength(2);
    expect(records[0]).toMatchObject({
      tool: "read",
      args: { filePath: "README.md" },
    });
    expect(records[1]).toMatchObject({
      tool: "bash",
      args: { command: "pwd" },
    });
  });

  it("uses directory before worktree for sandbox-local persistence", async () => {
    const directory = await tempWorktree();
    const hooks = await DefaultRecordToolCallPlugin({
      ...pluginContext("/"),
      directory,
    });

    await expect(
      hooks["tool.execute.before"]?.(
        { tool: "bash", sessionID: "ses_test", callID: "call_test" },
        { args: { command: "pwd" } },
      ),
    ).rejects.toThrow("Blocked tool call after persisting: bash");

    const [record] = await readRecords(directory);

    expect(record).toMatchObject({
      tool: "bash",
      args: { command: "pwd" },
    });
  });
});
