import { cac } from "cac";
import { z } from "zod";
import { spawn } from "node:child_process";
import { copyFile, cp, mkdir, mkdtemp, readFile, stat, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createLogger, type Logger, silentLogger } from "./logger.js";

let logger: Logger = silentLogger;

class CleanCliError extends Error {
  override name = "CleanCliError";
}

class UsageError extends CleanCliError {
  override name = "UsageError";
}

class ConfigValidationError extends CleanCliError {
  override name = "ConfigValidationError";
}

function isCleanCliError(error: unknown): boolean {
  return error instanceof CleanCliError || isCacUsageError(error);
}

function isCacUsageError(error: unknown): boolean {
  return error instanceof Error && error.name === "CACError";
}

export type Path = string;

type Writer = {
  write(text: string): unknown;
};

type CliIO = {
  stdout: Writer;
  stderr: Writer;
};

export interface SingleAgentSandboxSourceFiles {
  sourceConfigFile: Path;
  sourceAgentFile: Path;
}

export interface CreateSingleAgentSandboxLayoutArgs {
  sandboxRoot: Path;
}

export interface SingleAgentSandboxLayout {
  sandboxRoot: Path;
  configHome: Path;
  dataHome: Path;
  cacheHome: Path;
  stateHome: Path;
  opencodeConfigDir: Path;
  pluginDir: Path;
  agentDir: Path;
  worktree: Path;
  output: Path;
  sandboxConfigFile: Path;
}

export interface SingleAgentSandboxSpec extends SingleAgentSandboxSourceFiles {
  sourceRoot: Path;
  sandboxRoot: Path;
  agentName: string;
  prompt: string;
}

export interface PreparedSingleAgentSandbox {
  layout: SingleAgentSandboxLayout;
  sandboxPluginFiles: readonly Path[];
  sandboxAgentFile: Path;
}

export type AgentCopySpec = {
  agentName: string;
  sourceAgentFile: Path;
};

export interface MultiAgentSandboxSpec {
  sourceRoot: Path;
  sandboxRoot: Path;
  sourceConfigFile: Path;
  agents: readonly AgentCopySpec[];
}

export interface PreparedSandbox {
  layout: SingleAgentSandboxLayout;
  sandboxPluginFiles: readonly Path[];
  sandboxAgentFiles: Readonly<Record<string, Path>>;
}

export interface RunSingleAgentInSandboxArgs {
  layout: SingleAgentSandboxLayout;
  agentName: string;
  prompt: string;
}

export type RunDeps = {
  env?: NodeJS.ProcessEnv;
  cwd?: Path;
};

type ScenarioFile = {
  name: string;
  primaryAgent: string;
  config?: Path;
  agents: Record<string, Path>;
  promptFile: Path;
  fixtureDir?: Path;
  expectedFile: Path;
  scriptedSubagents?: Record<string, string[]>;
  transcript?: TraceEvent[];
};

type ScenarioBundle = {
  file: Path;
  dir: Path;
  scenario: ScenarioFile;
  prompt: string;
  expected: ExpectedAssertions;
};

type TaskCallTrace = {
  agent: string;
  prompt: string;
  output: string;
};

type ToolCallTrace = {
  tool: string;
  phase?: string;
};

type TraceEvent =
  | ({ type: "task" } & TaskCallTrace)
  | ({ type: "tool" } & ToolCallTrace)
  | { type: "final_response"; content: string };

type AssertionSpec =
  | { name: string; type: "taskPromptExcludes"; agent: string; forbidden: string[] }
  | { name: string; type: "taskPromptIncludes"; agent: string; required: string[] }
  | { name: string; type: "finalResponseExcludes"; forbidden: string[] }
  | { name: string; type: "finalResponseIncludes"; required: string[] }
  | { name: string; type: "hasReadonlyToolAfterApproval" }
  | { name: string; type: "finalResponseDoesNotClaimSuccessWithoutFinalCheck" };

type ExpectedAssertions = {
  assertions: AssertionSpec[];
};

type AssertionResult = {
  name: string;
  passed: boolean;
  message?: string;
};

type EvaluationResult = {
  status: number;
  score_inputs: {
    task_calls: TaskCallTrace[];
    reviewer_prompts: string[];
    planner_prompts: string[];
    implementer_prompts: string[];
    readonly_tools_after_approval: ToolCallTrace[];
    final_response: string;
  };
  assertions: AssertionResult[];
};

const Command = {
  Hello: "hello",
  HelloWorldSandbox: "hello-world",
  SingleAgent: "single-agent",
  Scenario: "scenario",
  Evaluate: "evaluate",
} as const;

const HelloWorldPrompt = "Respond with hello world.";

type Command = (typeof Command)[keyof typeof Command];

const defaultIO: CliIO = {
  stdout: process.stdout,
  stderr: process.stderr,
};

function currentPackageRoot(): Path {
  const modulePath = fileURLToPath(import.meta.url);
  const moduleDir = path.dirname(modulePath);

  return path.basename(moduleDir) === "dist"
    ? path.dirname(path.dirname(moduleDir))
    : path.dirname(moduleDir);
}

/**
 * Creates the isolated XDG layout used by OpenCode without resolving or copying
 * any source files. Source-specific sandbox file paths are derived by callers.
 */
export async function createSingleAgentSandboxLayout(
  args: CreateSingleAgentSandboxLayoutArgs,
): Promise<SingleAgentSandboxLayout> {
  const layout = deriveSingleAgentSandboxLayout(args);
  const { sandboxRoot } = layout;
  const log = logger.bind({ sandboxRoot });

  log.info("sandbox.layout.create.start");

  await Promise.all([
    mkdir(layout.pluginDir, { recursive: true }),
    mkdir(layout.agentDir, { recursive: true }),
    mkdir(layout.dataHome, { recursive: true }),
    mkdir(layout.cacheHome, { recursive: true }),
    mkdir(layout.stateHome, { recursive: true }),
    mkdir(layout.worktree, { recursive: true }),
    mkdir(layout.output, { recursive: true }),
  ]);

  log.info("sandbox.layout.create.done", {
    configHome: layout.configHome,
    dataHome: layout.dataHome,
    cacheHome: layout.cacheHome,
    stateHome: layout.stateHome,
    opencodeConfigDir: layout.opencodeConfigDir,
    worktree: layout.worktree,
    output: layout.output,
  });

  return layout;
}

function deriveSingleAgentSandboxLayout(
  args: CreateSingleAgentSandboxLayoutArgs,
): SingleAgentSandboxLayout {
  const sandboxRoot = path.resolve(args.sandboxRoot);
  const configHome = path.join(sandboxRoot, "config");
  const dataHome = path.join(sandboxRoot, "data");
  const cacheHome = path.join(sandboxRoot, "cache");
  const stateHome = path.join(sandboxRoot, "state");
  const opencodeConfigDir = path.join(configHome, "opencode");
  const pluginDir = path.join(opencodeConfigDir, "plugins");
  const agentDir = path.join(opencodeConfigDir, "agents");
  const worktree = path.join(sandboxRoot, "worktree");
  const output = path.join(sandboxRoot, "output");

  return {
    sandboxRoot,
    configHome,
    dataHome,
    cacheHome,
    stateHome,
    opencodeConfigDir,
    pluginDir,
    agentDir,
    worktree,
    output,
    sandboxConfigFile: path.join(opencodeConfigDir, "opencode.json"),
  };
}

function resolveFromRoot(sourceRoot: Path, filePath: Path): Path {
  return path.isAbsolute(filePath) ? filePath : path.join(sourceRoot, filePath);
}

type ConfiguredLocalPlugin = {
  entry: string;
  sourceFile: Path;
  sandboxFile: Path;
};

function isRelativeLocalPluginEntry(entry: unknown): entry is string {
  return (
    typeof entry === "string" &&
    (entry.startsWith("./") ||
      entry.startsWith("../") ||
      entry.startsWith("plugins/"))
  );
}

function isInsideDirectory(parent: Path, child: Path): boolean {
  const relative = path.relative(parent, child);
  return (
    relative === "" ||
    (!relative.startsWith("..") && !path.isAbsolute(relative))
  );
}

async function assertFileExists(
  file: Path,
  configuredEntry: string,
): Promise<void> {
  try {
    const fileStat = await stat(file);
    if (!fileStat.isFile()) {
      throw new Error("not a file");
    }
  } catch {
    throw new ConfigValidationError(
      `Configured local plugin does not exist: ${configuredEntry} -> ${file}`,
    );
  }
}

// OpenCode accepts plugin as either a single entry or an array; normalize to an array for sandbox copying.
const OpenCodeConfigSchema = z.object({
  plugin: z
    .union([z.string().transform((entry) => [entry]), z.array(z.string())])
    .optional()
    .default([]),
});

async function resolveConfiguredLocalPlugins(
  sourceConfigFile: Path,
  layout: SingleAgentSandboxLayout,
): Promise<ConfiguredLocalPlugin[]> {
  let configText: string;
  try {
    configText = await readFile(sourceConfigFile, "utf8");
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new ConfigValidationError(
      `Could not read config file ${sourceConfigFile}: ${message}`,
    );
  }

  let parsedConfig: unknown;
  try {
    parsedConfig = JSON.parse(configText);
  } catch {
    throw new ConfigValidationError(
      `Could not parse config file ${sourceConfigFile}`,
    );
  }

  const parseResult = OpenCodeConfigSchema.safeParse(parsedConfig);
  if (!parseResult.success)
    throw new ConfigValidationError(
      `Could not parse config file ${sourceConfigFile}`,
    );

  const pluginEntries = parseResult.data.plugin;

  // Parse the plugins to find if there are local plugins to copy
  const sourceConfigDir = path.dirname(sourceConfigFile);
  const sandboxConfigDir = path.dirname(layout.sandboxConfigFile);

  return pluginEntries
    .filter((entry): entry is string => {
      if (typeof entry === "string" && path.isAbsolute(entry)) {
        throw new ConfigValidationError(
          `Absolute local plugin paths are not supported in sandbox config: ${entry}`,
        );
      }

      return isRelativeLocalPluginEntry(entry);
    })
    .map((entry) => {
      const sandboxFile = path.resolve(sandboxConfigDir, entry);

      if (!isInsideDirectory(layout.pluginDir, sandboxFile)) {
        throw new ConfigValidationError(
          `Configured local plugin escapes sandbox plugin directory: ${entry} -> ${sandboxFile}`,
        );
      }

      return {
        entry,
        sourceFile: path.resolve(sourceConfigDir, entry),
        sandboxFile,
      };
    });
}

function assertSafeAgentName(agentName: string): void {
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]*$/.test(agentName)) {
    throw new ConfigValidationError(`Invalid agent name: ${agentName}`);
  }
}

async function assertSourceFileExists(file: Path, label: string): Promise<void> {
  try {
    const fileStat = await stat(file);
    if (!fileStat.isFile()) {
      throw new Error("not a file");
    }
  } catch {
    throw new ConfigValidationError(`${label} does not exist: ${file}`);
  }
}

async function requirePromptSource(
  sourceRoot: Path,
  options: { prompt?: string; promptFile?: Path },
): Promise<string> {
  if (options.prompt && options.promptFile) {
    throw new UsageError("Use only one of --prompt or --prompt-file");
  }
  if (options.promptFile) {
    return readFile(resolveFromRoot(sourceRoot, options.promptFile), "utf8");
  }
  if (options.prompt) {
    return options.prompt;
  }
  throw new UsageError("--prompt or --prompt-file is required");
}

function parseJsonFile<T>(file: Path, label: string): Promise<T> {
  return readFile(file, "utf8").then((text) => {
    try {
      return JSON.parse(text) as T;
    } catch {
      throw new ConfigValidationError(`Could not parse ${label} ${file}`);
    }
  });
}

async function readScenarioBundle(
  scenarioFile: Path,
): Promise<ScenarioBundle> {
  const file = path.resolve(scenarioFile);
  const dir = path.dirname(file);
  const scenario = await parseJsonFile<ScenarioFile>(file, "scenario file");
  const prompt = await readFile(resolveFromRoot(dir, scenario.promptFile), "utf8");
  const expected = await parseJsonFile<ExpectedAssertions>(
    resolveFromRoot(dir, scenario.expectedFile),
    "expected file",
  );

  return { file, dir, scenario, prompt, expected };
}

export async function defaultHelloWorldSpec(
  sourceRoot: Path,
  sandboxRoot: Path,
): Promise<SingleAgentSandboxSpec> {
  return {
    sourceRoot,
    sandboxRoot,
    agentName: "hello-world",
    prompt: HelloWorldPrompt,
    sourceConfigFile: path.join(sourceRoot, "opencode.json"),
    sourceAgentFile: path.join(
      sourceRoot,
      "sandbox",
      "fixtures",
      "agents",
      "hello-world.md",
    ),
  };
}

export async function prepareSingleAgentSandbox(
  spec: SingleAgentSandboxSpec,
): Promise<PreparedSingleAgentSandbox> {
  const prepared = await prepareMultiAgentSandbox({
    sourceRoot: spec.sourceRoot,
    sandboxRoot: spec.sandboxRoot,
    sourceConfigFile: spec.sourceConfigFile,
    agents: [
      { agentName: spec.agentName, sourceAgentFile: spec.sourceAgentFile },
    ],
  });

  return {
    layout: prepared.layout,
    sandboxPluginFiles: prepared.sandboxPluginFiles,
    sandboxAgentFile: prepared.sandboxAgentFiles[spec.agentName],
  };
}

export async function prepareMultiAgentSandbox(
  spec: MultiAgentSandboxSpec,
): Promise<PreparedSandbox> {
  for (const agent of spec.agents) {
    assertSafeAgentName(agent.agentName);
  }

  const validationLayout = deriveSingleAgentSandboxLayout({
    sandboxRoot: spec.sandboxRoot,
  });
  const configuredPlugins = await resolveConfiguredLocalPlugins(
    spec.sourceConfigFile,
    validationLayout,
  );
  await Promise.all(
    configuredPlugins.map((plugin) =>
      assertFileExists(plugin.sourceFile, plugin.entry),
    ),
  );
  await Promise.all(
    spec.agents.map((agent) =>
      assertSourceFileExists(agent.sourceAgentFile, `Agent ${agent.agentName}`),
    ),
  );

  const log = logger.bind({
    agentNames: spec.agents.map((agent) => agent.agentName),
    sandboxRoot: spec.sandboxRoot,
    sourceRoot: spec.sourceRoot,
  });

  log.info("sandbox.prepare.start");

  const layout = await createSingleAgentSandboxLayout({
    sandboxRoot: spec.sandboxRoot,
  });

  await copyFile(spec.sourceConfigFile, layout.sandboxConfigFile);
  await Promise.all(
    configuredPlugins.map(async (plugin) => {
      await mkdir(path.dirname(plugin.sandboxFile), { recursive: true });
      await copyFile(plugin.sourceFile, plugin.sandboxFile);
    }),
  );
  const sandboxPluginFiles = configuredPlugins.map(
    (plugin) => plugin.sandboxFile,
  );

  const sandboxAgentFiles: Record<string, Path> = {};
  await Promise.all(
    spec.agents.map(async (agent) => {
      const sandboxAgentFile = path.join(layout.agentDir, `${agent.agentName}.md`);
      await copyFile(agent.sourceAgentFile, sandboxAgentFile);
      sandboxAgentFiles[agent.agentName] = sandboxAgentFile;
    }),
  );

  log.info("sandbox.prepare.done", {
    sandboxConfigFile: layout.sandboxConfigFile,
    sandboxPluginFiles,
    sandboxAgentFiles,
  });

  return { layout, sandboxPluginFiles, sandboxAgentFiles };
}

export async function runSingleAgentInSandbox(
  args: RunSingleAgentInSandboxArgs,
  io: CliIO,
  deps: RunDeps = {},
): Promise<number> {
  const log = logger.bind({
    agentName: args.agentName,
    sandboxRoot: args.layout.sandboxRoot,
    worktree: args.layout.worktree,
  });
  const env = {
    ...process.env,
    ...deps.env,
    XDG_CONFIG_HOME: args.layout.configHome,
    XDG_DATA_HOME: args.layout.dataHome,
    XDG_CACHE_HOME: args.layout.cacheHome,
    XDG_STATE_HOME: args.layout.stateHome,
  };

  return new Promise((resolve) => {
    log.info("opencode.run.start", { promptLength: args.prompt.length });
    const child = spawn(
      "opencode",
      [
        "run",
        "--dir",
        args.layout.worktree,
        "--agent",
        args.agentName,
        args.prompt,
      ],
      {
        cwd: deps.cwd ?? args.layout.worktree,
        env,
        stdio: "inherit",
      },
    );

    child.on("error", (error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") {
        log.error("opencode.run.error", {
          code: error.code,
          message: error.message,
        });
        io.stderr.write("opencode CLI was not found on PATH\n");
        resolve(127);
        return;
      }

      log.error("opencode.run.error", {
        code: error.code,
        message: error.message,
      });
      io.stderr.write(`Failed to run opencode: ${error.message}\n`);
      resolve(1);
    });

    child.on("exit", (code, signal) => {
      if (code !== null) {
        log.info("opencode.run.exit", { status: code });
        resolve(code);
        return;
      }

      log.warn("opencode.run.signal", { signal });
      io.stderr.write(`opencode exited from signal ${signal ?? "unknown"}\n`);
      resolve(1);
    });
  });
}

async function writeCapturedArtifacts(
  layout: SingleAgentSandboxLayout,
  result: { status: number; stdout: string; stderr: string; command: string[] },
): Promise<void> {
  await mkdir(layout.output, { recursive: true });
  await Promise.all([
    writeFile(path.join(layout.output, "stdout.txt"), result.stdout),
    writeFile(path.join(layout.output, "stderr.txt"), result.stderr),
    writeFile(path.join(layout.output, "final-response.md"), result.stdout),
    writeFile(
      path.join(layout.output, "status.json"),
      `${JSON.stringify({ status: result.status }, null, 2)}\n`,
    ),
    writeFile(
      path.join(layout.output, "metadata.json"),
      `${JSON.stringify({ command: result.command, worktree: layout.worktree }, null, 2)}\n`,
    ),
    writeFile(
      path.join(layout.output, "result.json"),
      `${JSON.stringify(result, null, 2)}\n`,
    ),
  ]);
}

async function runCapturedOpencodeInSandbox(
  args: RunSingleAgentInSandboxArgs,
  io: CliIO,
  deps: RunDeps = {},
): Promise<number> {
  const command = [
    "run",
    "--dir",
    args.layout.worktree,
    "--agent",
    args.agentName,
    args.prompt,
  ];
  const env = {
    ...process.env,
    ...deps.env,
    XDG_CONFIG_HOME: args.layout.configHome,
    XDG_DATA_HOME: args.layout.dataHome,
    XDG_CACHE_HOME: args.layout.cacheHome,
    XDG_STATE_HOME: args.layout.stateHome,
    OPENCODE_SANDBOX_OUTPUT_DIR: args.layout.output,
    OPENCODE_SANDBOX_TRACE_FILE: path.join(args.layout.output, "transcript.jsonl"),
  };

  return new Promise((resolve) => {
    const child = spawn("opencode", command, {
      cwd: deps.cwd ?? args.layout.worktree,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";

    child.stdout?.on("data", (chunk: Buffer) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr?.on("data", (chunk: Buffer) => {
      stderr += chunk.toString("utf8");
    });

    child.on("error", async (error: NodeJS.ErrnoException) => {
      const status = error.code === "ENOENT" ? 127 : 1;
      const message =
        error.code === "ENOENT"
          ? "opencode CLI was not found on PATH\n"
          : `Failed to run opencode: ${error.message}\n`;
      stderr += message;
      io.stderr.write(message);
      await writeCapturedArtifacts(args.layout, { status, stdout, stderr, command });
      resolve(status);
    });

    child.on("exit", async (code, signal) => {
      const status = code ?? 1;
      if (code === null) {
        stderr += `opencode exited from signal ${signal ?? "unknown"}\n`;
      }
      await writeCapturedArtifacts(args.layout, { status, stdout, stderr, command });
      resolve(status);
    });
  });
}

function parseAgentCandidates(raw?: string | string[]): Record<string, Path> {
  const entries = (raw === undefined ? [] : Array.isArray(raw) ? raw : [raw]).filter(
    (entry): entry is string => typeof entry === "string",
  );
  const candidates: Record<string, Path> = {};

  for (const entry of entries) {
    const separator = entry.indexOf("=");
    if (separator <= 0 || separator === entry.length - 1) {
      throw new UsageError(`Invalid --agent-candidate value: ${entry}`);
    }
    const agentName = entry.slice(0, separator);
    assertSafeAgentName(agentName);
    candidates[agentName] = path.resolve(entry.slice(separator + 1));
  }

  return candidates;
}

async function prepareScenarioSandbox(args: {
  sourceRoot: Path;
  sandboxRoot: Path;
  bundle: ScenarioBundle;
  agentCandidates?: Record<string, Path>;
}): Promise<PreparedSandbox> {
  const scenario = args.bundle.scenario;
  const candidates = args.agentCandidates ?? {};
  const agents = Object.entries(scenario.agents).map(([agentName, agentFile]) => ({
    agentName,
    sourceAgentFile: candidates[agentName] ?? resolveFromRoot(args.sourceRoot, agentFile),
  }));
  const prepared = await prepareMultiAgentSandbox({
    sourceRoot: args.sourceRoot,
    sandboxRoot: args.sandboxRoot,
    sourceConfigFile: resolveFromRoot(args.sourceRoot, scenario.config ?? "opencode.json"),
    agents,
  });

  if (scenario.fixtureDir) {
    await cp(resolveFromRoot(args.bundle.dir, scenario.fixtureDir), prepared.layout.worktree, {
      recursive: true,
      force: true,
    });
  }

  if (scenario.scriptedSubagents) {
    await installSandboxTracePlugin(prepared.layout, scenario.scriptedSubagents);
  }

  await writeFile(
    path.join(prepared.layout.output, "metadata.json"),
    `${JSON.stringify(
      {
        scenario: scenario.name,
        primaryAgent: scenario.primaryAgent,
        promptFile: scenario.promptFile,
        candidates: Object.keys(candidates),
      },
      null,
      2,
    )}\n`,
  );

  return prepared;
}

async function installSandboxTracePlugin(
  layout: SingleAgentSandboxLayout,
  scriptedSubagents: Record<string, string[]>,
): Promise<void> {
  const pluginFile = path.join(layout.pluginDir, "sandbox-task-trace.js");
  await writeFile(
    pluginFile,
    `// Generated by sandbox cli-v2 for deterministic scenario traces.\nexport const scriptedSubagents = ${JSON.stringify(scriptedSubagents, null, 2)};\n`,
  );

  const config = JSON.parse(await readFile(layout.sandboxConfigFile, "utf8")) as {
    plugin?: unknown;
  };
  const plugin = Array.isArray(config.plugin)
    ? config.plugin
    : typeof config.plugin === "string"
      ? [config.plugin]
      : [];
  config.plugin = [...plugin, "./plugins/sandbox-task-trace.js"];
  await writeFile(layout.sandboxConfigFile, `${JSON.stringify(config, null, 2)}\n`);
}

function syntheticTraceFromScenario(bundle: ScenarioBundle): TraceEvent[] {
  if (bundle.scenario.transcript) {
    return bundle.scenario.transcript;
  }
  const events: TraceEvent[] = [];
  for (const [agent, outputs] of Object.entries(bundle.scenario.scriptedSubagents ?? {})) {
    outputs.forEach((output, index) => {
      events.push({
        type: "task",
        agent,
        prompt: index === 0 ? bundle.prompt : output,
        output,
      });
    });
  }
  return events;
}

async function readTraceEvents(layout: SingleAgentSandboxLayout): Promise<TraceEvent[]> {
  const transcriptFile = path.join(layout.output, "transcript.jsonl");
  try {
    const text = await readFile(transcriptFile, "utf8");
    return text
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => JSON.parse(line) as TraceEvent);
  } catch {
    return [];
  }
}

function evaluateTrace(
  events: TraceEvent[],
  expected: ExpectedAssertions,
  finalResponse: string,
  status: number,
): EvaluationResult {
  const taskCalls = events.filter((event): event is { type: "task" } & TaskCallTrace => event.type === "task");
  const finalEvent = [...events]
    .reverse()
    .find((event): event is { type: "final_response"; content: string } => event.type === "final_response");
  const resolvedFinalResponse = finalEvent?.content ?? finalResponse;
  const approvedIndex = events.findIndex(
    (event) => event.type === "task" && event.agent === "reviewer" && /verdict:\s*APPROVED/i.test(event.output),
  );
  const readonlyToolsAfterApproval = events
    .slice(approvedIndex >= 0 ? approvedIndex + 1 : events.length)
    .filter((event): event is { type: "tool" } & ToolCallTrace =>
      event.type === "tool" && ["read", "glob", "grep", "list"].includes(event.tool),
    )
    .map(({ tool, phase }) => ({ tool, phase }));
  const score_inputs = {
    task_calls: taskCalls.map(({ agent, prompt, output }) => ({ agent, prompt, output })),
    reviewer_prompts: taskCalls.filter((call) => call.agent === "reviewer").map((call) => call.prompt),
    planner_prompts: taskCalls.filter((call) => call.agent === "planner").map((call) => call.prompt),
    implementer_prompts: taskCalls.filter((call) => call.agent === "implementer").map((call) => call.prompt),
    readonly_tools_after_approval: readonlyToolsAfterApproval,
    final_response: resolvedFinalResponse,
  };
  const assertions = expected.assertions.map((assertion) =>
    runAssertion(assertion, taskCalls, resolvedFinalResponse, readonlyToolsAfterApproval, approvedIndex >= 0),
  );

  return { status, score_inputs, assertions };
}

function runAssertion(
  assertion: AssertionSpec,
  taskCalls: TaskCallTrace[],
  finalResponse: string,
  readonlyToolsAfterApproval: ToolCallTrace[],
  hasApproval: boolean,
): AssertionResult {
  switch (assertion.type) {
    case "taskPromptExcludes": {
      const prompts = taskCalls.filter((call) => call.agent === assertion.agent).map((call) => call.prompt);
      const forbidden = assertion.forbidden.find((text) => prompts.some((prompt) => prompt.includes(text)));
      return forbidden
        ? { name: assertion.name, passed: false, message: `${assertion.agent} prompt contained forbidden text: ${forbidden}` }
        : { name: assertion.name, passed: true };
    }
    case "taskPromptIncludes": {
      const prompts = taskCalls.filter((call) => call.agent === assertion.agent).map((call) => call.prompt).join("\n");
      const missing = assertion.required.find((text) => !prompts.includes(text));
      return missing
        ? { name: assertion.name, passed: false, message: `${assertion.agent} prompt missed required text: ${missing}` }
        : { name: assertion.name, passed: true };
    }
    case "finalResponseExcludes": {
      const forbidden = assertion.forbidden.find((text) => finalResponse.includes(text));
      return forbidden
        ? { name: assertion.name, passed: false, message: `final response contained forbidden text: ${forbidden}` }
        : { name: assertion.name, passed: true };
    }
    case "finalResponseIncludes": {
      const missing = assertion.required.find((text) => !finalResponse.includes(text));
      return missing
        ? { name: assertion.name, passed: false, message: `final response missed required text: ${missing}` }
        : { name: assertion.name, passed: true };
    }
    case "hasReadonlyToolAfterApproval":
      return readonlyToolsAfterApproval.length > 0
        ? { name: assertion.name, passed: true }
        : { name: assertion.name, passed: false, message: "no read-only tool call after reviewer approval" };
    case "finalResponseDoesNotClaimSuccessWithoutFinalCheck": {
      const claimsSuccess = /\b(success|successful|done|completed|ready)\b/i.test(finalResponse);
      return hasApproval && readonlyToolsAfterApproval.length === 0 && claimsSuccess
        ? { name: assertion.name, passed: false, message: "final response claimed success without a final read-only check" }
        : { name: assertion.name, passed: true };
    }
  }
}

function requiredOption(value: string | undefined, name: string): string {
  if (!value) {
    throw new UsageError(`${name} is required`);
  }

  return value;
}

export function createCli(io: CliIO = defaultIO, deps: RunDeps = {}) {
  const cli = cac("cli-v2");

  cli.command(Command.Hello, "Print hello world").action(() => {
    io.stdout.write("hello world\n");
    return 0;
  });

  cli
    .command(
      Command.SingleAgent,
      "Run one explicit agent in an isolated OpenCode sandbox",
    )
    .option("--orig <path>", "Source OpenCode config root")
    .option("--dest <path>", "Sandbox destination directory")
    .option(
      "--config <path>",
      "Source OpenCode config file, relative to --orig unless absolute",
    )
    .option("--agent <name>", "OpenCode agent name to run")
    .option(
      "--agent-file <path>",
      "Source agent file, relative to --orig unless absolute",
    )
    .option("--prompt <text>", "Prompt/message passed to opencode run")
    .option("--prompt-file <path>", "Prompt file, relative to --orig unless absolute")
    .action(
      async (options: {
        orig?: Path;
        dest?: Path;
        config?: Path;
        agent?: string;
        agentFile?: Path;
        prompt?: string;
        promptFile?: Path;
      }) => {
        const sourceRoot = path.resolve(options.orig ?? currentPackageRoot());
        const sandboxRoot = path.resolve(
          options.dest ??
            (await mkdtemp(path.join(os.tmpdir(), "opencode-cli-v2-"))),
        );
        const agentName = requiredOption(options.agent, "--agent");
        const prompt = await requirePromptSource(sourceRoot, options);
        const spec: SingleAgentSandboxSpec = {
          sourceRoot,
          sandboxRoot,
          agentName,
          prompt,
          sourceConfigFile: resolveFromRoot(
            sourceRoot,
            options.config ?? "opencode.json",
          ),
          sourceAgentFile: resolveFromRoot(
            sourceRoot,
            requiredOption(options.agentFile, "--agent-file"),
          ),
        };
        const prepared = await prepareSingleAgentSandbox(spec);

        return runSingleAgentInSandbox(
          {
            layout: prepared.layout,
            agentName: spec.agentName,
            prompt: spec.prompt,
          },
          io,
          deps,
        );
      },
    );

  cli
    .command(Command.Scenario, "Prepare a deterministic scenario sandbox")
    .option("--orig <path>", "Source OpenCode config root")
    .option("--dest <path>", "Sandbox destination directory")
    .option("--scenario <path>", "Scenario JSON file")
    .option("--agent-candidate <agent=file>", "Candidate agent replacement")
    .action(
      async (options: {
        orig?: Path;
        dest?: Path;
        scenario?: Path;
        agentCandidate?: string | string[];
      }) => {
        const sourceRoot = path.resolve(options.orig ?? currentPackageRoot());
        const sandboxRoot = path.resolve(
          options.dest ??
            (await mkdtemp(path.join(os.tmpdir(), "opencode-cli-v2-"))),
        );
        const bundle = await readScenarioBundle(requiredOption(options.scenario, "--scenario"));
        const candidates = parseAgentCandidates(options.agentCandidate);
        await prepareScenarioSandbox({ sourceRoot, sandboxRoot, bundle, agentCandidates: candidates });
        return 0;
      },
    );

  cli
    .command(Command.Evaluate, "Run and evaluate a scenario sandbox")
    .option("--orig <path>", "Source OpenCode config root")
    .option("--dest <path>", "Sandbox destination directory")
    .option("--scenario <path>", "Scenario JSON file")
    .option("--agent-candidate <agent=file>", "Candidate agent replacement")
    .option("--json", "Write evaluation JSON to stdout")
    .action(
      async (options: {
        orig?: Path;
        dest?: Path;
        scenario?: Path;
        agentCandidate?: string | string[];
        json?: boolean;
      }) => {
        const sourceRoot = path.resolve(options.orig ?? currentPackageRoot());
        const sandboxRoot = path.resolve(
          options.dest ??
            (await mkdtemp(path.join(os.tmpdir(), "opencode-cli-v2-"))),
        );
        const bundle = await readScenarioBundle(requiredOption(options.scenario, "--scenario"));
        const candidates = parseAgentCandidates(options.agentCandidate);
        const prepared = await prepareScenarioSandbox({ sourceRoot, sandboxRoot, bundle, agentCandidates: candidates });
        let status = 0;
        let events = syntheticTraceFromScenario(bundle);
        let finalResponse = "";

        if (!bundle.scenario.scriptedSubagents) {
          status = await runCapturedOpencodeInSandbox(
            {
              layout: prepared.layout,
              agentName: bundle.scenario.primaryAgent,
              prompt: bundle.prompt,
            },
            io,
            deps,
          );
          events = await readTraceEvents(prepared.layout);
          try {
            finalResponse = await readFile(path.join(prepared.layout.output, "final-response.md"), "utf8");
          } catch {
            finalResponse = "";
          }
        } else {
          finalResponse = events.find((event): event is { type: "final_response"; content: string } => event.type === "final_response")?.content ?? "";
          await writeFile(
            path.join(prepared.layout.output, "transcript.jsonl"),
            events.map((event) => JSON.stringify(event)).join("\n") + (events.length ? "\n" : ""),
          );
          await writeCapturedArtifacts(prepared.layout, {
            status,
            stdout: finalResponse,
            stderr: "",
            command: ["scripted", bundle.scenario.name],
          });
        }

        const evaluation = evaluateTrace(events, bundle.expected, finalResponse, status);
        await writeFile(
          path.join(prepared.layout.output, "evaluation.json"),
          `${JSON.stringify(evaluation, null, 2)}\n`,
        );
        if (options.json) {
          io.stdout.write(`${JSON.stringify(evaluation, null, 2)}\n`);
          return 0;
        }
        return evaluation.assertions.every((assertion) => assertion.passed) ? status : 1;
      },
    );

  cli
    .command(
      Command.HelloWorldSandbox,
      "Run the hello-world agent in an isolated OpenCode sandbox",
    )
    .option("--orig <path>", "Source OpenCode config root")
    .option("--dest <path>", "Sandbox destination directory")
    .action(async (options: { orig?: Path; dest?: Path }) => {
      const sourceRoot = path.resolve(options.orig ?? currentPackageRoot());
      const sandboxRoot = path.resolve(
        options.dest ??
          (await mkdtemp(path.join(os.tmpdir(), "opencode-cli-v2-"))),
      );
      const spec = await defaultHelloWorldSpec(sourceRoot, sandboxRoot);
      const prepared = await prepareSingleAgentSandbox(spec);

      return runSingleAgentInSandbox(
        {
          layout: prepared.layout,
          agentName: spec.agentName,
          prompt: spec.prompt,
        },
        io,
        deps,
      );
    });

  cli.help();
  return cli;
}

export async function runCli(
  argv = process.argv,
  io: CliIO = defaultIO,
  deps: RunDeps = {},
): Promise<number> {
  const originalConsoleInfo = console.info;
  const originalLogger = logger;
  logger = createLogger();
  const cli = createCli(io, deps);

  try {
    console.info = (message?: unknown) => {
      io.stdout.write(`${message ?? ""}\n`);
    };

    // Only parse, do not run when doing run: false
    const parsed = cli.parse(argv, { run: false });

    if (!cli.matchedCommand && parsed.args.length > 0) {
      io.stderr.write(`Unknown command: ${parsed.args[0]}\n`);
      cli.outputHelp();
      return 1;
    }

    if (parsed.options.help) {
      return 0;
    }

    if (!cli.matchedCommand) {
      io.stderr.write("No command provided.\n");
      cli.outputHelp();
      return 1;
    }

    const result = await cli.runMatchedCommand();
    return typeof result === "number" ? result : 0;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (!isCleanCliError(error)) {
      logger.error("cli.error", { message });
    }
    io.stderr.write(`${message}\n`);
    return 1;
  } finally {
    console.info = originalConsoleInfo;
    logger = originalLogger;
  }
}

// When Node executes this file directly, process.argv[1] is the filesystem path
// to this script. Convert it to a file:// URL so it can be compared with
// import.meta.url, which is always represented as a URL in ES modules.
const entrypoint = process.argv[1] ? pathToFileURL(process.argv[1]).href : "";

// Only run the CLI entrypoint for direct execution, not when tests or other
// modules import createCli/runCli. Assigning process.exitCode lets Node finish
// normal cleanup before exiting with the status returned by runCli().
if (import.meta.url === entrypoint) {
  process.exitCode = await runCli();
}
