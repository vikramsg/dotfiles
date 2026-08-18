import { mkdtemp, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { buildRecordToolCallPlugin } from "./record-tool-call.ts";
import type { PluginInput } from "@opencode-ai/plugin/v1";

describe("RecordToolCallPlugin", () => {
  const metadata = {
    output_dir: ".test-tool-calls",
    output_file: "calls.jsonl",
  };

  const toolCallInput = {
    tool: "bash",
    sessionID: "ses_test",
    callID: "call_test",
  };

  const toolCallOutput = {
    args: { command: "printf plugin-demo" },
  };

  it("registers a tool.execute.before hook", async () => {
    // Given a plugin configured to persist tool calls.
    const worktree = await mkdtemp(
      path.join(os.tmpdir(), "persist-tool-call-test-"),
    );
    const plugin = buildRecordToolCallPlugin(metadata);
    const context: PluginInput = {
      client: {} as never,
      project: {} as never,
      directory: worktree,
      worktree,
      experimental_workspace: { register: () => undefined },
      serverUrl: new URL("http://localhost"),
      $: {} as never,
    };

    // When OpenCode initializes the plugin.
    const hooks = await plugin(context);

    // Then it exposes the before-tool hook OpenCode will call.
    expect(hooks["tool.execute.before"]).toBeTypeOf("function");
  });

  it("persists the attempted tool call before blocking execution", async () => {
    // Given a plugin initialized with a sandbox-local worktree.
    const worktree = await mkdtemp(
      path.join(os.tmpdir(), "persist-tool-call-test-"),
    );
    const plugin = buildRecordToolCallPlugin(metadata);
    const context = {
      client: {} as never,
      project: {} as never,
      directory: worktree,
      worktree,
      experimental_workspace: {} as never,
      serverUrl: new URL("http://localhost"),
      $: {} as never,
    };
    const hooks = await plugin(context);
    const beforeTool = hooks["tool.execute.before"];

    if (!beforeTool) throw new Error("tool.execute.before hook missing");

    // When OpenCode attempts to execute a tool.
    await expect(beforeTool(toolCallInput, toolCallOutput)).rejects.toThrow(
      "Blocked tool call after persisting: bash",
    );

    // Then the attempted call is persisted to JSONL before execution is blocked.
    const text = await readFile(
      path.join(worktree, metadata.output_dir, metadata.output_file),
      "utf8",
    );
    const record = JSON.parse(text.trim());

    expect(record).toMatchObject({
      hook: "tool.execute.before",
      sessionID: toolCallInput.sessionID,
      callID: toolCallInput.callID,
      tool: toolCallInput.tool,
      args: toolCallOutput.args,
    });
    expect(typeof (record as { at?: unknown }).at).toBe("string");
  });
});
