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

type CapturedRunResult = {
  status: number;
  stdout: string;
  stderr: string;
  command: string[];
  timedOut: boolean;
  signal?: NodeJS.Signals | null;
};

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
  sequence?: number;
};

type ToolCallTrace = {
  tool: string;
  phase?: string;
  args?: string;
  output?: string;
  result?: string;
  success?: boolean;
  error?: string;
};

type TraceEvent =
  | ({ type: "task" } & TaskCallTrace)
  | ({ type: "tool" } & ToolCallTrace)
  | { type: "trace_error"; message: string; agent?: string; sequence?: number }
  | { type: "final_response"; content: string };

type TraceReadResult =
  | { events: TraceEvent[]; traceErrors: [] }
  | { events: []; traceErrors: string[] };

type RequiredTraceValidation = {
  events: TraceEvent[];
  traceErrors: string[];
};

type TraceValidationResult =
  | { ok: true; event: TraceEvent }
  | { ok: false; message: string };

type AssertionSpec =
  | { name: string; type: "taskPromptExcludes"; agent: string; forbidden: string[] }
  | { name: string; type: "taskPromptIncludes"; agent: string; required: string[] }
  | { name: string; type: "taskCallCount"; agent: string; equals?: number; atLeast?: number }
  | { name: string; type: "finalResponseExcludes"; forbidden: string[] }
  | { name: string; type: "finalResponseIncludes"; required: string[] }
  | { name: string; type: "hasReadonlyToolAfterApproval" }
  | { name: string; type: "readonlyToolOutputIncludes"; required: string[] }
  | { name: string; type: "finalResponseRequiresLatestReadonlyCheck"; required?: string[]; forbidden?: string[] }
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
  passed: boolean;
  status: number;
  timed_out?: boolean;
  error?: string;
  score_inputs: {
    task_calls: TaskCallTrace[];
    reviewer_prompts: string[];
    planner_prompts: string[];
    implementer_prompts: string[];
    readonly_tools_after_approval: ToolCallTrace[];
    final_response: string;
  };
  trace_errors: string[];
  assertions: AssertionResult[];
};

function evaluationPassed(evaluation: EvaluationResult): boolean {
  return (
    evaluation.status === 0 &&
    evaluation.timed_out !== true &&
    evaluation.trace_errors.length === 0 &&
    evaluation.assertions.every((assertion) => assertion.passed)
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) > 0;
}

function validateOptionalPositiveInteger(value: Record<string, unknown>, key: string): string | undefined {
  return value[key] === undefined || isPositiveInteger(value[key])
    ? undefined
    : `${key} must be a positive integer`;
}

function validateOptionalString(value: Record<string, unknown>, key: string): string | undefined {
  return value[key] === undefined || typeof value[key] === "string"
    ? undefined
    : `${key} must be a string`;
}

function validateRequiredString(value: Record<string, unknown>, key: string): string | undefined {
  return typeof value[key] === "string" ? undefined : `${key} must be a string`;
}

function validateTraceEvent(value: unknown): TraceValidationResult {
  if (!isRecord(value)) {
    return { ok: false, message: "event must be an object" };
  }

  switch (value.type) {
    case "task": {
      const error =
        validateRequiredString(value, "agent") ??
        validateRequiredString(value, "prompt") ??
        validateRequiredString(value, "output") ??
        validateOptionalPositiveInteger(value, "sequence");
      return error ? { ok: false, message: error } : { ok: true, event: value as TraceEvent };
    }
    case "tool": {
      const error =
        validateRequiredString(value, "tool") ??
        validateOptionalString(value, "phase") ??
        validateOptionalString(value, "args") ??
        validateOptionalString(value, "output") ??
        validateOptionalString(value, "result") ??
        validateOptionalString(value, "error") ??
        (value.success === undefined || typeof value.success === "boolean" ? undefined : "success must be a boolean");
      return error ? { ok: false, message: error } : { ok: true, event: value as TraceEvent };
    }
    case "trace_error": {
      const error =
        validateRequiredString(value, "message") ??
        validateOptionalString(value, "agent") ??
        validateOptionalPositiveInteger(value, "sequence");
      return error ? { ok: false, message: error } : { ok: true, event: value as TraceEvent };
    }
    case "final_response": {
      const error = validateRequiredString(value, "content");
      return error ? { ok: false, message: error } : { ok: true, event: value as TraceEvent };
    }
    default:
      return { ok: false, message: "unknown event type" };
  }
}

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
  result: CapturedRunResult,
): Promise<void> {
  await mkdir(layout.output, { recursive: true });
  const metadataFile = path.join(layout.output, "metadata.json");
  let existingMetadata: Record<string, unknown> = {};
  try {
    existingMetadata = JSON.parse(await readFile(metadataFile, "utf8")) as Record<string, unknown>;
  } catch {
    existingMetadata = {};
  }
  await Promise.all([
    writeFile(path.join(layout.output, "stdout.txt"), result.stdout),
    writeFile(path.join(layout.output, "stderr.txt"), result.stderr),
    writeFile(path.join(layout.output, "final-response.md"), result.stdout),
    writeFile(
      path.join(layout.output, "status.json"),
      `${JSON.stringify({ status: result.status, timed_out: result.timedOut, signal: result.signal ?? null }, null, 2)}\n`,
    ),
    writeFile(
      metadataFile,
      `${JSON.stringify({ ...existingMetadata, command: result.command, worktree: layout.worktree }, null, 2)}\n`,
    ),
    writeFile(
      path.join(layout.output, "result.json"),
      `${JSON.stringify(result, null, 2)}\n`,
    ),
  ]);
}

async function runCapturedOpencodeInSandbox(
  args: RunSingleAgentInSandboxArgs & { timeoutMs?: number },
  io: CliIO,
  deps: RunDeps = {},
): Promise<CapturedRunResult> {
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
    let timedOut = false;
    let settled = false;
    let killTimer: NodeJS.Timeout | undefined;
    const timeoutTimer = args.timeoutMs
      ? setTimeout(() => {
          timedOut = true;
          stderr += `opencode timed out after ${args.timeoutMs}ms\n`;
          child.kill("SIGTERM");
          killTimer = setTimeout(() => child.kill("SIGKILL"), 1000);
        }, args.timeoutMs)
      : undefined;

    async function finish(status: number, signal: NodeJS.Signals | null = null) {
      if (settled) return;
      settled = true;
      if (timeoutTimer) clearTimeout(timeoutTimer);
      if (killTimer) clearTimeout(killTimer);
      const result: CapturedRunResult = { status, stdout, stderr, command, timedOut, signal };
      await writeCapturedArtifacts(args.layout, result);
      resolve(result);
    }

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
      await finish(status);
    });

    child.on("exit", async (code, signal) => {
      const status = timedOut ? 124 : (code ?? 1);
      if (code === null) {
        stderr += `opencode exited from signal ${signal ?? "unknown"}\n`;
      }
      await finish(status, signal);
    });
  });
}

function parsePositiveIntegerOption(raw: unknown, name: string): number | undefined {
  if (raw === undefined || raw === false) return undefined;
  const text = String(raw);
  if (!/^[1-9]\d*$/.test(text)) {
    throw new UsageError(`${name} must be a positive integer`);
  }
  return Number(text);
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

function validateAgentCandidates(
  candidates: Record<string, Path>,
  scenario: ScenarioFile,
): void {
  const scenarioAgentNames = new Set(Object.keys(scenario.agents));

  for (const agentName of Object.keys(candidates)) {
    if (!scenarioAgentNames.has(agentName)) {
      throw new UsageError(`Unknown --agent-candidate agent: ${agentName}`);
    }
  }
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
    await installSandboxTracePlugin(prepared.layout, scenario.scriptedSubagents, scenario.primaryAgent);
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
  primaryAgent: string,
): Promise<void> {
  const pluginFile = path.join(layout.pluginDir, "sandbox-task-trace.js");
  await writeFile(
    pluginFile,
    `// Generated by sandbox cli-v2 for deterministic scenario trace expectations.
import fs from "node:fs"
import path from "node:path"

const scriptedSubagents = ${JSON.stringify(scriptedSubagents, null, 2)}
const primaryAgent = ${JSON.stringify(primaryAgent)}
const consumed = Object.fromEntries(Object.keys(scriptedSubagents).map((agent) => [agent, 0]))
const readOnlyTools = new Set(["read", "glob", "grep", "list"])
let reviewerApproved = false

function traceFile() {
  return process.env.OPENCODE_SANDBOX_TRACE_FILE || path.join(process.env.OPENCODE_SANDBOX_OUTPUT_DIR || process.cwd(), "transcript.jsonl")
}

function appendEvent(event) {
  const file = traceFile()
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.appendFileSync(file, JSON.stringify(event) + "\\n")
}

function normalizeText(value) {
  if (typeof value === "string") return value
  if (value === undefined || value === null) return ""
  if (Array.isArray(value)) return value.map(normalizeText).join("\\n")
  if (typeof value === "object") {
    if (typeof value.text === "string") return value.text
    if (typeof value.content === "string") return value.content
    if (typeof value.output === "string") return value.output
  }
  return JSON.stringify(value)
}

function normalizeJson(value) {
  if (value === undefined || value === null) return ""
  if (typeof value === "string") return value
  try {
    return JSON.stringify(value)
  } catch {
    return normalizeText(value)
  }
}

function taskAgent(args) {
  return args?.subagent_type || args?.subagentType || args?.agent || args?.agentName || ""
}

function taskPrompt(args) {
  for (const key of ["prompt", "description", "message", "input", "task"]) {
    const text = normalizeText(args?.[key])
    if (text) return text
  }
  return normalizeText(args)
}

function finalContent(input, output) {
  const message = output?.message ?? input?.message
  if (!message || message.role !== "assistant") return ""
  const agent = message.agent ?? message.agentName ?? message.metadata?.agent
  if (agent !== primaryAgent && agent !== "orchestrator") return ""
  return normalizeText(message.content ?? message.parts)
}

function validateUnconsumedExpectations() {
  for (const [agent, expected] of Object.entries(scriptedSubagents)) {
    const observed = consumed[agent] || 0
    if (observed < expected.length) {
      appendEvent({
        type: "trace_error",
        agent,
        sequence: observed + 1,
        message: "Unconsumed scripted task output for " + agent + " at call " + (observed + 1),
      })
    }
  }
}

process.once("exit", validateUnconsumedExpectations)

function recordTaskExpectation(agent, sequence, observedOutput) {
  const expected = scriptedSubagents[agent]
  if (!expected) {
    appendEvent({ type: "trace_error", agent, sequence, message: "Unexpected task call for " + agent })
    return
  }
  const expectedOutput = expected[sequence - 1]
  if (expectedOutput === undefined) {
    appendEvent({ type: "trace_error", agent, sequence, message: "Exhausted scripted task outputs for " + agent + " at call " + sequence })
    return
  }
  if (observedOutput !== expectedOutput) {
    appendEvent({ type: "trace_error", agent, sequence, message: "Scripted output mismatch for " + agent + " call " + sequence })
  }
}

export async function SandboxTracePlugin() {
  return {
    "tool.execute.after": async (input, output) => {
      const tool = input?.tool || ""
      if (tool === "task") {
        const agent = taskAgent(input?.args)
        if (!agent) return output
        const index = consumed[agent] || 0
        consumed[agent] = index + 1
        const observedOutput = normalizeText(output?.output ?? output?.content ?? output?.message ?? output)
        const sequence = index + 1
        if (agent === "reviewer" && /verdict:\\s*APPROVED\\b/i.test(observedOutput)) reviewerApproved = true
        appendEvent({ type: "task", agent, prompt: taskPrompt(input?.args), output: observedOutput, sequence })
        recordTaskExpectation(agent, sequence, observedOutput)
        return output
      }
      if (reviewerApproved && readOnlyTools.has(tool)) {
        const event = { type: "tool", tool, phase: "after-approval", args: normalizeJson(input?.args) }
        const outputText = normalizeText(output?.output ?? output?.content ?? output?.message)
        const resultText = normalizeText(output?.result ?? output)
        if (outputText) event.output = outputText
        if (resultText) event.result = resultText
        if (typeof output?.success === "boolean") event.success = output.success
        if (output?.error !== undefined) event.error = normalizeText(output.error)
        appendEvent(event)
      }
      return output
    },
    "chat.message": async (input, output) => {
      const content = finalContent(input, output)
      if (content) appendEvent({ type: "final_response", content })
      return output
    },
  }
}

export const SandboxTraceStubPlugin = SandboxTracePlugin
`,
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

async function readTraceEventsForEvaluation(layout: SingleAgentSandboxLayout): Promise<TraceReadResult> {
  const transcriptFile = path.join(layout.output, "transcript.jsonl");
  let text: string;
  try {
    text = await readFile(transcriptFile, "utf8");
  } catch {
    return { events: [], traceErrors: [`Required trace file was not written: ${transcriptFile}`] };
  }

  const events: TraceEvent[] = [];
  for (const [index, line] of text.split(/\r?\n/).entries()) {
    if (!line) continue;
    let parsed: unknown;
    try {
      parsed = JSON.parse(line);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return { events: [], traceErrors: [`Malformed trace ${transcriptFile} line ${index + 1}: ${message}`] };
    }
    const validated = validateTraceEvent(parsed);
    if (!validated.ok) {
      return { events: [], traceErrors: [`Invalid trace ${transcriptFile} line ${index + 1}: ${validated.message}`] };
    }
    events.push(validated.event);
  }
  if (events.length === 0) {
    return { events: [], traceErrors: [`Required trace file contained no events: ${transcriptFile}`] };
  }
  return { events, traceErrors: [] };
}

async function readAndValidateRequiredTrace(
  layout: SingleAgentSandboxLayout,
): Promise<RequiredTraceValidation> {
  const trace = await readTraceEventsForEvaluation(layout);
  const traceEventErrors: string[] = [];
  for (const event of trace.events) {
    if (event.type === "trace_error") traceEventErrors.push(event.message);
  }

  return {
    events: trace.events,
    traceErrors: [...trace.traceErrors, ...traceEventErrors],
  };
}

function latestReadonlyToolAfterLatestApproval(events: TraceEvent[]): ToolCallTrace | undefined {
  let latestApprovalIndex = -1;
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event.type === "task" && event.agent === "reviewer" && /verdict:\s*APPROVED/i.test(event.output)) {
      latestApprovalIndex = index;
      break;
    }
  }

  if (latestApprovalIndex < 0) return undefined;

  return events
    .slice(latestApprovalIndex + 1)
    .filter((event): event is { type: "tool" } & ToolCallTrace =>
      event.type === "tool" && ["read", "glob", "grep", "list"].includes(event.tool),
    )
    .at(-1);
}

function evaluateTrace(
  events: TraceEvent[],
  expected: ExpectedAssertions,
  _finalResponse: string,
  status: number,
  traceReadErrors: string[] = [],
): EvaluationResult {
  const taskCalls = events.filter((event): event is { type: "task" } & TaskCallTrace => event.type === "task");
  const traceErrors = events.filter((event): event is { type: "trace_error"; message: string; agent?: string; sequence?: number } => event.type === "trace_error");
  const finalEvent = [...events]
    .reverse()
    .find((event): event is { type: "final_response"; content: string } => event.type === "final_response");
  const resolvedFinalResponse = finalEvent?.content ?? "";
  const approvedIndex = events.findIndex(
    (event) => event.type === "task" && event.agent === "reviewer" && /verdict:\s*APPROVED/i.test(event.output),
  );
  const readonlyToolsAfterApproval = events
    .slice(approvedIndex >= 0 ? approvedIndex + 1 : events.length)
    .filter((event): event is { type: "tool" } & ToolCallTrace =>
      event.type === "tool" && ["read", "glob", "grep", "list"].includes(event.tool),
    )
    .map(({ tool, phase, args, output, result, success, error }) => ({ tool, phase, args, output, result, success, error }));
  const score_inputs = {
    task_calls: taskCalls.map(({ agent, prompt, output, sequence }) => ({ agent, prompt, output, sequence })),
    reviewer_prompts: taskCalls.filter((call) => call.agent === "reviewer").map((call) => call.prompt),
    planner_prompts: taskCalls.filter((call) => call.agent === "planner").map((call) => call.prompt),
    implementer_prompts: taskCalls.filter((call) => call.agent === "implementer").map((call) => call.prompt),
    readonly_tools_after_approval: readonlyToolsAfterApproval,
    final_response: resolvedFinalResponse,
  };
  const assertions = expected.assertions.map((assertion) =>
    runAssertion(assertion, events, taskCalls, resolvedFinalResponse, readonlyToolsAfterApproval, approvedIndex >= 0),
  );
  if (traceErrors.length > 0) {
    assertions.push({
      name: "trace_expectations",
      passed: false,
      message: traceErrors.map((event) => event.message).join("; "),
    });
  }
  for (const message of traceReadErrors) {
    assertions.push({ name: "trace", passed: false, message });
  }

  return { passed: false, status, score_inputs, trace_errors: [...traceErrors.map((event) => event.message), ...traceReadErrors], assertions };
}

function runAssertion(
  assertion: AssertionSpec,
  events: TraceEvent[],
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
    case "taskCallCount": {
      const count = taskCalls.filter((call) => call.agent === assertion.agent).length;
      if (assertion.equals !== undefined && count !== assertion.equals) {
        return { name: assertion.name, passed: false, message: `${assertion.agent} task call count was ${count}, expected ${assertion.equals}` };
      }
      if (assertion.atLeast !== undefined && count < assertion.atLeast) {
        return { name: assertion.name, passed: false, message: `${assertion.agent} task call count was ${count}, expected at least ${assertion.atLeast}` };
      }
      return { name: assertion.name, passed: true };
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
    case "readonlyToolOutputIncludes": {
      const observed = readonlyToolsAfterApproval
        .map((tool) => [tool.args, tool.output, tool.result, tool.error].filter(Boolean).join("\n"))
        .join("\n");
      const missing = assertion.required.find((text) => !observed.includes(text));
      return missing
        ? { name: assertion.name, passed: false, message: `read-only tool trace missed required text: ${missing}` }
        : { name: assertion.name, passed: true };
    }
    case "finalResponseRequiresLatestReadonlyCheck": {
      const claimsSuccess = /\b(success|successful|done|completed|ready|handled)\b/i.test(finalResponse);
      if (!claimsSuccess) return { name: assertion.name, passed: true };
      const latestCheck = latestReadonlyToolAfterLatestApproval(events);
      if (!hasApproval || !latestCheck) {
        return { name: assertion.name, passed: false, message: "final response claimed success without a final read-only check after the latest approval" };
      }
      const checkText = [latestCheck.args, latestCheck.output, latestCheck.result, latestCheck.error].filter(Boolean).join("\n");
      const dirtyText = assertion.forbidden?.find((text) => checkText.includes(text));
      const checkShowsIncomplete = /\b(pending|incomplete|not\s+ready|fail(?:ed|ing)?|dirty|uncommitted)\b/i.test(checkText);
      if (dirtyText || checkShowsIncomplete) {
        return { name: assertion.name, passed: false, message: dirtyText ? `latest final read-only check contained forbidden text: ${dirtyText}` : "final response claimed success despite an incomplete latest final read-only check" };
      }
      const missing = assertion.required?.find((text) => !checkText.includes(text));
      return missing
        ? { name: assertion.name, passed: false, message: `latest final read-only check missed required text: ${missing}` }
        : { name: assertion.name, passed: true };
    }
    case "finalResponseDoesNotClaimSuccessWithoutFinalCheck": {
      const claimsSuccess = /\b(success|successful|done|completed|ready)\b/i.test(finalResponse);
      const checkText = readonlyToolsAfterApproval
        .map((tool) => [tool.output, tool.result, tool.error].filter(Boolean).join("\n"))
        .join("\n");
      const checkShowsIncomplete = /\b(pending|incomplete|not\s+ready|fail(?:ed|ing)?|dirty|uncommitted)\b/i.test(checkText);
      return hasApproval && claimsSuccess && (readonlyToolsAfterApproval.length === 0 || checkShowsIncomplete)
        ? { name: assertion.name, passed: false, message: checkShowsIncomplete ? "final response claimed success despite an incomplete final read-only check" : "final response claimed success without a final read-only check" }
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
    .command(Command.Scenario, "Run a deterministic scenario sandbox")
    .option("--orig <path>", "Source OpenCode config root")
    .option("--dest <path>", "Sandbox destination directory")
    .option("--scenario <path>", "Scenario JSON file")
    .option("--agent-candidate <agent=file>", "Candidate agent replacement")
    .option("--timeout-ms <number>", "Maximum opencode runtime in milliseconds")
    .option("--prepare-only", "Prepare the sandbox without running opencode")
    .action(
      async (options: {
        orig?: Path;
        dest?: Path;
        scenario?: Path;
        agentCandidate?: string | string[];
        timeoutMs?: string;
        prepareOnly?: boolean;
      }) => {
        const sourceRoot = path.resolve(options.orig ?? currentPackageRoot());
        const sandboxRoot = path.resolve(
          options.dest ??
            (await mkdtemp(path.join(os.tmpdir(), "opencode-cli-v2-"))),
        );
        const bundle = await readScenarioBundle(requiredOption(options.scenario, "--scenario"));
        const candidates = parseAgentCandidates(options.agentCandidate);
        validateAgentCandidates(candidates, bundle.scenario);
        const timeoutMs = parsePositiveIntegerOption(options.timeoutMs, "--timeout-ms");
        const prepared = await prepareScenarioSandbox({ sourceRoot, sandboxRoot, bundle, agentCandidates: candidates });
        if (options.prepareOnly) return 0;
        const run = await runCapturedOpencodeInSandbox(
          { layout: prepared.layout, agentName: bundle.scenario.primaryAgent, prompt: bundle.prompt, timeoutMs },
          io,
          deps,
        );
        if (bundle.scenario.scriptedSubagents && !run.timedOut) {
          const trace = await readAndValidateRequiredTrace(prepared.layout);
          if (trace.traceErrors.length > 0) {
            for (const message of trace.traceErrors) {
              io.stderr.write(`${message}\n`);
            }
            return run.status === 0 ? 1 : run.status;
          }
        }
        return run.status;
      },
    );

  cli
    .command(Command.Evaluate, "Run and evaluate a scenario sandbox")
    .option("--orig <path>", "Source OpenCode config root")
    .option("--dest <path>", "Sandbox destination directory")
    .option("--scenario <path>", "Scenario JSON file")
    .option("--agent-candidate <agent=file>", "Candidate agent replacement")
    .option("--timeout-ms <number>", "Maximum opencode runtime in milliseconds")
    .option("--json", "Write evaluation JSON to stdout")
    .action(
      async (options: {
        orig?: Path;
        dest?: Path;
        scenario?: Path;
        agentCandidate?: string | string[];
        timeoutMs?: string;
        json?: boolean;
      }) => {
        const sourceRoot = path.resolve(options.orig ?? currentPackageRoot());
        const sandboxRoot = path.resolve(
          options.dest ??
            (await mkdtemp(path.join(os.tmpdir(), "opencode-cli-v2-"))),
        );
        const bundle = await readScenarioBundle(requiredOption(options.scenario, "--scenario"));
        const candidates = parseAgentCandidates(options.agentCandidate);
        validateAgentCandidates(candidates, bundle.scenario);
        const timeoutMs = parsePositiveIntegerOption(options.timeoutMs, "--timeout-ms");
        const prepared = await prepareScenarioSandbox({ sourceRoot, sandboxRoot, bundle, agentCandidates: candidates });
        const run = await runCapturedOpencodeInSandbox(
          {
            layout: prepared.layout,
            agentName: bundle.scenario.primaryAgent,
            prompt: bundle.prompt,
            timeoutMs,
          },
          io,
          deps,
        );
        const trace = run.timedOut
          ? { events: [], traceErrors: [] }
          : await readTraceEventsForEvaluation(prepared.layout);
        const evaluation = evaluateTrace(trace.events, bundle.expected, run.stdout, run.status, trace.traceErrors);
        evaluation.timed_out = run.timedOut;
        evaluation.passed = evaluationPassed(evaluation);
        await writeFile(
          path.join(prepared.layout.output, "evaluation.json"),
          `${JSON.stringify(evaluation, null, 2)}\n`,
        );
        if (options.json) {
          io.stdout.write(`${JSON.stringify(evaluation, null, 2)}\n`);
        }
        return evaluation.passed ? 0 : 1;
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
