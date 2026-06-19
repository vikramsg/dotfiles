import { spawn } from "node:child_process";
import {
  copyFile,
  mkdir,
  mkdtemp,
  readFile,
  stat,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { cac } from "cac";
import { z } from "zod";
import {
  isInsideDirectory,
  readJsonFile,
  resolveFromRoot,
} from "./file-system.ts";
import { createLogger, silentLogger, type Logger } from "./logger.ts";
import {
  copyScenarioFixture,
  loadScenario,
  ScenarioValidationError,
} from "./scenario.ts";
import type { Path } from "./types.ts";
import { log } from "node:console";

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
  return (
    error instanceof CleanCliError ||
    error instanceof ScenarioValidationError ||
    isCacUsageError(error)
  );
}

function isCacUsageError(error: unknown): boolean {
  return error instanceof Error && error.name === "CACError";
}

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
  sourceAuthFile: Path;
}

export interface CreateSingleAgentSandboxLayoutArgs {
  sandboxRoot: Path;
}

// FIXME: Document where normally these dirs are and what each one is required for
export interface SingleAgentSandboxLayout {
  sandboxRoot: Path;
  configHome: Path;
  dataHome: Path;
  cacheHome: Path;
  stateHome: Path;
  shareHome: Path;
  opencodeConfigDir: Path;
  pluginDir: Path;
  agentDir: Path;
  worktree: Path;
  output: Path;
  sandboxConfigFile: Path;
  sandboxAuthFile: Path;
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

export interface RunSingleAgentInSandboxArgs {
  layout: SingleAgentSandboxLayout;
  agentName: string;
  prompt: string;
  timeoutMs?: number;
  metadata?: RunMetadataInput;
}

export type RunDeps = {
  env?: NodeJS.ProcessEnv;
  cwd?: Path;
};

type RunMetadataInput = {
  command: "single-agent" | "hello-world" | "scenario";
  sourceRoot?: Path;
  sourceConfigFile?: Path;
  sourceAgentFile?: Path;
  promptSource: "text" | "file";
  promptFile?: Path;
  scenarioName?: string;
  scenarioDir?: Path;
};

type RunArtifacts = {
  commandFile: Path;
  metadataFile: Path;
  stdoutFile: Path;
  stderrFile: Path;
  rawStatusFile: Path;
  statusFile: Path;
};

const Command = {
  Hello: "hello",
  HelloWorldSandbox: "hello-world",
  SingleAgent: "single-agent",
  Scenario: "scenario",
} as const;

const HelloWorldPrompt = "Respond with hello world.";

const defaultIO: CliIO = {
  stdout: process.stdout,
  stderr: process.stderr,
};

/**
 * CLI v2 runs from TypeScript source, not from emitted JavaScript. Keep root
 * resolution tied to this source file so fixture and scenario paths do not
 * silently depend on a build output directory.
 */
function currentCliV2Root(): Path {
  const modulePath = fileURLToPath(import.meta.url);
  return path.dirname(modulePath);
}

function currentOpencodeRoot(): Path {
  return path.resolve(currentCliV2Root(), "../..");
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

  // FIXME: Layout should have a dirs member so that we can just do mkdir(dirs)?
  await Promise.all([
    mkdir(layout.pluginDir, { recursive: true }),
    mkdir(layout.agentDir, { recursive: true }),
    mkdir(layout.dataHome, { recursive: true }),
    mkdir(layout.cacheHome, { recursive: true }),
    mkdir(layout.stateHome, { recursive: true }),
    mkdir(layout.shareHome, { recursive: true }),
    mkdir(layout.worktree, { recursive: true }),
    mkdir(layout.output, { recursive: true }),
  ]);

  log.info("sandbox.layout.create.done", {
    configHome: layout.configHome,
    dataHome: layout.dataHome,
    cacheHome: layout.cacheHome,
    stateHome: layout.stateHome,
    shareHome: layout.shareHome,
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
  const shareHome = path.join(sandboxRoot, "share");
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
    shareHome,
    opencodeConfigDir,
    pluginDir,
    agentDir,
    worktree,
    output,
    sandboxConfigFile: path.join(opencodeConfigDir, "opencode.json"),
    sandboxAuthFile: path.join(shareHome, "auth.json"),
  };
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

async function ensureCopyableSourceFile(
  file: Path,
  failureMessage: string,
): Promise<void> {
  try {
    const fileStat = await stat(file);
    if (!fileStat.isFile()) {
      throw new Error("not a file");
    }
  } catch {
    throw new ConfigValidationError(failureMessage);
  }
}

// OpenCode accepts plugin as either a single entry or an array; normalize to an array for sandbox copying.
const OpenCodeConfigSchema = z.object({
  plugin: z
    .union([z.string().transform((entry) => [entry]), z.array(z.string())])
    .optional()
    .default([]),
});

/**
 * OpenCode config entries are copied as-is into the sandbox. For local plugin
 * entries, copy only files whose normalized destination remains inside the
 * sandbox plugin directory; otherwise the copied config could point outside
 * the isolated XDG tree.
 */
async function resolveConfiguredLocalPlugins(
  sourceConfigFile: Path,
  layout: SingleAgentSandboxLayout,
): Promise<ConfiguredLocalPlugin[]> {
  let parsedConfig: unknown;
  try {
    parsedConfig = await readJsonFile(sourceConfigFile, "config file");
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new ConfigValidationError(message);
  }

  const parseResult = OpenCodeConfigSchema.safeParse(parsedConfig);
  if (!parseResult.success) {
    throw new ConfigValidationError(
      `Could not parse config file ${sourceConfigFile}`,
    );
  }

  const pluginEntries = parseResult.data.plugin;
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

function ensureSafeAgentName(agentName: string): void {
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]*$/.test(agentName)) {
    throw new ConfigValidationError(`Invalid agent name: ${agentName}`);
  }
}

export async function defaultHelloWorldSpec(
  sandboxRoot: Path,
  sourceRoot = currentOpencodeRoot(),
): Promise<SingleAgentSandboxSpec> {
  return {
    sourceRoot,
    sandboxRoot,
    agentName: "hello-world",
    prompt: HelloWorldPrompt,
    sourceConfigFile: path.join(sourceRoot, "opencode.json"),
    sourceAgentFile: path.join(
      currentCliV2Root(),
      "fixtures",
      "agents",
      "hello-world.md",
    ),
  };
}

/**
 * Validate source files and local plugin destinations before creating the
 * sandbox layout. Setup failures should be clean and should not leave a
 * partially populated sandbox behind.
 */
export async function prepareSingleAgentSandbox(
  spec: SingleAgentSandboxSpec,
): Promise<PreparedSingleAgentSandbox> {
  ensureSafeAgentName(spec.agentName);

  const validationLayout = deriveSingleAgentSandboxLayout({
    sandboxRoot: spec.sandboxRoot,
  });
  const configuredPlugins = await resolveConfiguredLocalPlugins(
    spec.sourceConfigFile,
    validationLayout,
  );
  await Promise.all(
    configuredPlugins.map((plugin) =>
      ensureCopyableSourceFile(
        plugin.sourceFile,
        `Configured local plugin does not exist: ${plugin.entry} -> ${plugin.sourceFile}`,
      ),
    ),
  );
  await ensureCopyableSourceFile(
    spec.sourceAgentFile,
    `Source agent file does not exist: ${spec.sourceAgentFile}`,
  );

  const log = logger.bind({
    agentName: spec.agentName,
    sandboxRoot: spec.sandboxRoot,
    sourceRoot: spec.sourceRoot,
  });

  log.info("sandbox.prepare.start");

  const layout = await createSingleAgentSandboxLayout({
    sandboxRoot: spec.sandboxRoot,
  });
  await ensureCopyableSourceFile(
    spec.sourceAuthFile,
    `auth.json file does not exist: ${spec.sourceAuthFile}`,
  );
  await copyFile(spec.sourceAuthFile, layout.sandboxAuthFile);

  const sandboxAgentFile = path.join(layout.agentDir, `${spec.agentName}.md`);

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

  await copyFile(spec.sourceAgentFile, sandboxAgentFile);

  log.info("sandbox.prepare.done", {
    sandboxConfigFile: layout.sandboxConfigFile,
    sandboxPluginFiles,
    sandboxAgentFile,
  });

  return { layout, sandboxPluginFiles, sandboxAgentFile };
}

function artifactPaths(layout: SingleAgentSandboxLayout): RunArtifacts {
  return {
    commandFile: path.join(layout.output, "command.txt"),
    metadataFile: path.join(layout.output, "metadata.json"),
    stdoutFile: path.join(layout.output, "stdout.txt"),
    stderrFile: path.join(layout.output, "stderr.txt"),
    rawStatusFile: path.join(layout.output, "opencode-exit-status.txt"),
    statusFile: path.join(layout.output, "exit-status.txt"),
  };
}

/**
 * The command artifact is for human reproduction only. The real OpenCode run
 * uses spawn argv directly and never executes this string through a shell.
 */
function shellQuote(value: string): string {
  if (/^[A-Za-z0-9_/:=.,@%+-]+$/.test(value)) return value;
  return `'${value.replaceAll("'", `'"'"'`)}'`;
}

async function writeRunArtifacts(
  files: RunArtifacts,
  args: readonly string[],
  metadata: Record<string, unknown>,
  stdoutText: string,
  stderrText: string,
  rawStatus: number,
  finalStatus: number,
): Promise<void> {
  await Promise.all([
    writeFile(
      files.commandFile,
      `${shellQuote("opencode")} ${args.map(shellQuote).join(" ")}\n`,
    ),
    writeFile(files.metadataFile, `${JSON.stringify(metadata, null, 2)}\n`),
    writeFile(files.stdoutFile, stdoutText),
    writeFile(files.stderrFile, stderrText),
    writeFile(files.rawStatusFile, `${rawStatus}\n`),
    writeFile(files.statusFile, `${finalStatus}\n`),
  ]);
}

/**
 * Run OpenCode with isolated XDG homes, mirror stdout/stderr to the caller,
 * and persist the same streams plus status files for later inspection.
 */
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
    XDG_SHARE_HOME: args.layout.shareHome,
  };
  const opencodeArgs = [
    "run",
    "--dir",
    args.layout.worktree,
    "--agent",
    args.agentName,
    args.prompt,
  ];
  const files = artifactPaths(args.layout);
  const metadata = {
    command: args.metadata?.command ?? "single-agent",
    agentName: args.agentName,
    sandboxRoot: args.layout.sandboxRoot,
    worktree: args.layout.worktree,
    timeoutMs: args.timeoutMs ?? null,
    ...args.metadata,
  };

  return new Promise((resolve) => {
    let settled = false;
    let stdoutText = "";
    let stderrText = "";
    let timeout: NodeJS.Timeout | undefined;

    /**
     * Spawn errors, process close, and timeout can race. Exactly one path may
     * write artifacts and resolve the command status.
     */
    const finish = (rawStatus: number, finalStatus = rawStatus) => {
      if (settled) return;
      settled = true;
      if (timeout) clearTimeout(timeout);
      writeRunArtifacts(
        files,
        opencodeArgs,
        metadata,
        stdoutText,
        stderrText,
        rawStatus,
        finalStatus,
      )
        .then(() => resolve(finalStatus))
        .catch((error: unknown) => {
          const message =
            error instanceof Error ? error.message : String(error);
          io.stderr.write(`Failed to write run artifacts: ${message}\n`);
          resolve(1);
        });
    };

    log.info("opencode.run.start", { promptLength: args.prompt.length });
    const child = spawn("opencode", opencodeArgs, {
      cwd: deps.cwd ?? args.layout.worktree,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });

    if (args.timeoutMs !== undefined) {
      timeout = setTimeout(() => {
        const message = `opencode timed out after ${args.timeoutMs}ms\n`;
        stderrText += message;
        io.stderr.write(message);
        child.kill();
        finish(124);
      }, args.timeoutMs);
    }

    child.stdout?.on("data", (chunk: Buffer) => {
      const text = chunk.toString();
      stdoutText += text;
      io.stdout.write(text);
    });

    child.stderr?.on("data", (chunk: Buffer) => {
      const text = chunk.toString();
      stderrText += text;
      io.stderr.write(text);
    });

    child.on("error", (error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") {
        log.error("opencode.run.error", {
          code: error.code,
          message: error.message,
        });
        const message = "opencode CLI was not found on PATH\n";
        stderrText += message;
        io.stderr.write(message);
        finish(127);
        return;
      }

      log.error("opencode.run.error", {
        code: error.code,
        message: error.message,
      });
      const message = `Failed to run opencode: ${error.message}\n`;
      stderrText += message;
      io.stderr.write(message);
      finish(1);
    });

    child.on("close", (code, signal) => {
      if (settled) return;
      if (code !== null) {
        log.info("opencode.run.exit", { status: code });
        finish(code);
        return;
      }

      log.warn("opencode.run.signal", { signal });
      const message = `opencode exited from signal ${signal ?? "unknown"}\n`;
      stderrText += message;
      io.stderr.write(message);
      finish(1);
    });
  });
}

function requiredOption(value: string | undefined, name: string): string {
  if (!value) {
    throw new UsageError(`${name} is required`);
  }

  return value;
}

async function readPrompt(options: {
  prompt?: string;
  promptFile?: string;
}): Promise<{ prompt: string; source: "text" | "file"; file?: Path }> {
  if (Boolean(options.prompt) === Boolean(options.promptFile)) {
    throw new UsageError("Use exactly one of --prompt or --prompt-file");
  }

  if (options.prompt !== undefined) {
    return { prompt: options.prompt, source: "text" };
  }

  const promptFile = path.resolve(
    requiredOption(options.promptFile, "--prompt-file"),
  );
  return {
    prompt: await readFile(promptFile, "utf8"),
    source: "file",
    file: promptFile,
  };
}

function parseTimeoutMs(
  value: string | number | undefined,
): number | undefined {
  if (value === undefined) return undefined;
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) {
    throw new UsageError("--timeout-ms must be a positive integer");
  }
  return parsed;
}

async function makeSandboxRoot(dest?: Path): Promise<Path> {
  return path.resolve(
    dest ?? (await mkdtemp(path.join(os.tmpdir(), "opencode-cli-v2-"))),
  );
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
    .option("--prompt-file <path>", "Prompt file passed to opencode run")
    .option("--timeout-ms <number>", "Maximum opencode runtime in milliseconds")
    .action(
      async (options: {
        orig?: Path;
        dest?: Path;
        config?: Path;
        agent?: string;
        agentFile?: Path;
        prompt?: string;
        promptFile?: Path;
        timeoutMs?: string;
      }) => {
        const timeoutMs = parseTimeoutMs(options.timeoutMs);
        const prompt = await readPrompt({
          prompt: options.prompt,
          promptFile: options.promptFile,
        });
        const sourceRoot = path.resolve(options.orig ?? currentOpencodeRoot());
        const sandboxRoot = await makeSandboxRoot(options.dest);
        const sourceConfigFile = resolveFromRoot(
          sourceRoot,
          options.config ?? "opencode.json",
        );
        const sourceAgentFile = resolveFromRoot(
          sourceRoot,
          requiredOption(options.agentFile, "--agent-file"),
        );
        const sourceAuthFile = resolveFromRoot(
          os.homedir(),
          ".local/share/opencode/auth.json",
        );
        const spec: SingleAgentSandboxSpec = {
          sourceRoot,
          sandboxRoot,
          agentName: requiredOption(options.agent, "--agent"),
          prompt: prompt.prompt,
          sourceConfigFile,
          sourceAgentFile,
          sourceAuthFile,
        };
        log.info("sourceAuthFile", { sourceAuthFile });
        const prepared = await prepareSingleAgentSandbox(spec);

        return runSingleAgentInSandbox(
          {
            layout: prepared.layout,
            agentName: spec.agentName,
            prompt: spec.prompt,
            timeoutMs,
            metadata: {
              command: "single-agent",
              sourceRoot,
              sourceConfigFile,
              sourceAgentFile,
              promptSource: prompt.source,
              promptFile: prompt.file,
            },
          },
          io,
          deps,
        );
      },
    );

  cli
    .command(
      Command.HelloWorldSandbox,
      "Run the hello-world agent in an isolated OpenCode sandbox",
    )
    .option("--orig <path>", "Source OpenCode config root")
    .option("--dest <path>", "Sandbox destination directory")
    .option("--timeout-ms <number>", "Maximum opencode runtime in milliseconds")
    .action(
      async (options: { orig?: Path; dest?: Path; timeoutMs?: string }) => {
        const timeoutMs = parseTimeoutMs(options.timeoutMs);
        const sourceRoot = path.resolve(options.orig ?? currentOpencodeRoot());
        const sandboxRoot = await makeSandboxRoot(options.dest);
        const spec = await defaultHelloWorldSpec(sandboxRoot, sourceRoot);
        const prepared = await prepareSingleAgentSandbox(spec);

        return runSingleAgentInSandbox(
          {
            layout: prepared.layout,
            agentName: spec.agentName,
            prompt: spec.prompt,
            timeoutMs,
            metadata: {
              command: "hello-world",
              sourceRoot,
              sourceConfigFile: spec.sourceConfigFile,
              sourceAgentFile: spec.sourceAgentFile,
              promptSource: "text",
            },
          },
          io,
          deps,
        );
      },
    );

  cli
    .command(`${Command.Scenario} <scenario-dir>`, "Run a saved sandbox recipe")
    .option("--dest <path>", "Sandbox destination directory")
    .option("--timeout-ms <number>", "Maximum opencode runtime in milliseconds")
    .action(
      async (
        scenarioDirArg: Path | undefined,
        options: { dest?: Path; timeoutMs?: string },
      ) => {
        const scenarioDir = path.resolve(
          requiredOption(scenarioDirArg, "<scenario-dir>"),
        );
        const timeoutMs = parseTimeoutMs(options.timeoutMs);
        const cliRoot = currentCliV2Root();
        const sourceRoot = currentOpencodeRoot();
        const scenario = await loadScenario({
          scenarioDir,
          cliRoot,
          defaultConfigFile: path.resolve(cliRoot, "../../opencode.json"),
        });
        const sandboxRoot = await makeSandboxRoot(options.dest);
        const spec: SingleAgentSandboxSpec = {
          sourceRoot,
          sandboxRoot,
          agentName: scenario.agent,
          prompt: scenario.prompt,
          sourceConfigFile: scenario.sourceConfigFile,
          sourceAgentFile: scenario.sourceAgentFile,
        };
        const prepared = await prepareSingleAgentSandbox(spec);

        await copyScenarioFixture(scenario, prepared.layout.worktree);

        return runSingleAgentInSandbox(
          {
            layout: prepared.layout,
            agentName: spec.agentName,
            prompt: spec.prompt,
            timeoutMs,
            metadata: {
              command: "scenario",
              sourceRoot,
              sourceConfigFile: scenario.sourceConfigFile,
              sourceAgentFile: scenario.sourceAgentFile,
              promptSource: "file",
              promptFile: scenario.promptFile,
              scenarioName: scenario.name,
              scenarioDir,
            },
          },
          io,
          deps,
        );
      },
    );

  cli.help();
  return cli;
}

/**
 * Tests inject IO writers instead of mutating process stdout/stderr. CAC help
 * writes through console methods, so temporarily route those through the same
 * injected IO contract and restore them after every run.
 */
export async function runCli(
  argv = process.argv,
  io: CliIO = defaultIO,
  deps: RunDeps = {},
): Promise<number> {
  const originalConsoleInfo = console.info;
  const originalConsoleLog = console.log;
  const originalLogger = logger;
  logger = createLogger();
  const cli = createCli(io, deps);

  try {
    console.info = (message?: unknown) => {
      io.stdout.write(`${message ?? ""}\n`);
    };
    console.log = (message?: unknown) => {
      io.stdout.write(`${message ?? ""}\n`);
    };

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
    console.log = originalConsoleLog;
    logger = originalLogger;
  }
}

// Direct execution needs a file URL comparison because import.meta.url is always URL-shaped in ES modules.
const entrypoint = process.argv[1] ? pathToFileURL(process.argv[1]).href : "";

if (import.meta.url === entrypoint) {
  process.exitCode = await runCli();
}
