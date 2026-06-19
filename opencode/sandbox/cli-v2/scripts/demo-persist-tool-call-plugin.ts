import { copyFile, mkdir, mkdtemp, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  prepareSingleAgentSandbox,
  runSingleAgentInSandbox,
  type SingleAgentSandboxSpec,
} from "../index.ts";

const cliRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const sourceRoot = path.resolve(cliRoot, "../..");
const prompt = "Use the bash tool to run: printf plugin-demo";

const sandboxRoot = await mkdtemp(
  path.join(os.tmpdir(), "opencode-tool-plugin-demo-"),
);
const sourceAgentFile = path.join(
  cliRoot,
  "fixtures",
  "agents",
  "tool-call-demo.md",
);
const sourcePluginFile = path.join(
  cliRoot,
  "fixtures",
  "plugins",
  "persist-tool-call-and-stop.ts",
);

const spec: SingleAgentSandboxSpec = {
  sourceRoot,
  sandboxRoot,
  agentName: "tool-call-demo",
  prompt,
  sourceConfigFile: path.join(sourceRoot, "opencode.json"),
  sourceAgentFile,
  sourceAuthFile: path.join(
    os.homedir(),
    ".local",
    "share",
    "opencode",
    "auth.json",
  ),
};

const prepared = await prepareSingleAgentSandbox(spec);
const sandboxPluginFile = path.join(
  prepared.layout.pluginDir,
  "persist-tool-call-and-stop.ts",
);

await mkdir(path.dirname(sandboxPluginFile), { recursive: true });
await copyFile(sourcePluginFile, sandboxPluginFile);

const status = await runSingleAgentInSandbox(
  {
    layout: prepared.layout,
    agentName: spec.agentName,
    prompt: spec.prompt,
    timeoutMs: 60_000,
    metadata: {
      command: "single-agent",
      sourceRoot,
      sourceConfigFile: spec.sourceConfigFile,
      sourceAgentFile,
      sourceAuthFile: spec.sourceAuthFile,
      sandboxConfigFile: prepared.layout.sandboxConfigFile,
      sandboxAgentFile: prepared.sandboxAgentFile,
      sandboxAuthFile: prepared.layout.sandboxAuthFile,
      promptSource: "text",
    },
  },
  {
    stdout: process.stdout,
    stderr: process.stderr,
  },
);

const persistedFile = path.join(
  prepared.layout.worktree,
  ".agents",
  "tool-call-blocks",
  "tool-calls.jsonl",
);

process.stdout.write(`\nPersisted blocked tool calls:\n${persistedFile}\n`);
try {
  process.stdout.write(await readFile(persistedFile, "utf8"));
} catch (error) {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`Could not read persisted tool calls: ${message}\n`);
}

process.exitCode = status;
