import { cac } from "cac";
import { readdir, stat } from "node:fs/promises";
import { spawn } from "node:child_process";
import { copyFile, mkdir, mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createLogger, type Logger, silentLogger } from "./logger.js";

let logger: Logger = silentLogger;

// Minimal generic single-agent sandbox runner for exercising one OpenCode agent in isolation.
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
  sourcePluginFiles: Path[];
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

export interface RunSingleAgentInSandboxArgs {
  layout: SingleAgentSandboxLayout;
  agentName: string;
  prompt: string;
}

export type RunDeps = {
  env?: NodeJS.ProcessEnv;
  cwd?: Path;
};

const Command = {
  Hello: "hello",
  HelloWorldSandbox: "hello-world",
  SingleAgent: "single-agent",
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
  const sandboxRoot = path.resolve(args.sandboxRoot);
  const log = logger.bind({ sandboxRoot });
  const configHome = path.join(sandboxRoot, "config");
  const dataHome = path.join(sandboxRoot, "data");
  const cacheHome = path.join(sandboxRoot, "cache");
  const stateHome = path.join(sandboxRoot, "state");
  const opencodeConfigDir = path.join(configHome, "opencode");
  const pluginDir = path.join(opencodeConfigDir, "plugins");
  const agentDir = path.join(opencodeConfigDir, "agents");
  const worktree = path.join(sandboxRoot, "worktree");
  const output = path.join(sandboxRoot, "output");

  log.info("sandbox.layout.create.start");

  await Promise.all([
    mkdir(pluginDir, { recursive: true }),
    mkdir(agentDir, { recursive: true }),
    mkdir(dataHome, { recursive: true }),
    mkdir(cacheHome, { recursive: true }),
    mkdir(stateHome, { recursive: true }),
    mkdir(worktree, { recursive: true }),
    mkdir(output, { recursive: true }),
  ]);

  log.info("sandbox.layout.create.done", {
    configHome,
    dataHome,
    cacheHome,
    stateHome,
    opencodeConfigDir,
    worktree,
    output,
  });

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

async function isDirectory(path: string): Promise<boolean> {
  try {
    return (await stat(path)).isDirectory();
  } catch {
    return false;
  }
}

export async function defaultHelloWorldSpec(
  sourceRoot: Path,
  sandboxRoot: Path,
): Promise<SingleAgentSandboxSpec> {
  const pluginDir = path.join(sourceRoot, "plugins");
  const pluginDirFiles = (await isDirectory(pluginDir))
    ? await readdir(pluginDir)
    : [];

  const pluginFiles = pluginDirFiles.filter(
    (entry) => path.extname(entry) === "js",
  );
  logger.debug("HelloWorldSpec", { pluginFiles });

  return {
    sourceRoot,
    sandboxRoot,
    agentName: "Hello World",
    prompt: HelloWorldPrompt,
    sourceConfigFile: path.join(sourceRoot, "opencode.json"),
    sourcePluginFiles: pluginFiles,
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
  const log = logger.bind({
    agentName: spec.agentName,
    sandboxRoot: spec.sandboxRoot,
    sourceRoot: spec.sourceRoot,
  });

  log.info("sandbox.prepare.start");

  const layout = await createSingleAgentSandboxLayout({
    sandboxRoot: spec.sandboxRoot,
  });
  const sandboxPluginFiles = spec.sourcePluginFiles.map((entry) =>
    path.join(layout.pluginDir, path.basename(entry)),
  );
  spec.sourcePluginFiles.map(
    async (entry) =>
      await copyFile(entry, path.join(layout.pluginDir, path.basename(entry))),
  );

  const sandboxAgentFile = path.join(layout.agentDir, `${spec.agentName}.md`);
  await copyFile(spec.sourceAgentFile, sandboxAgentFile);

  await copyFile(spec.sourceConfigFile, layout.sandboxConfigFile);
  await copyFile(spec.sourceAgentFile, sandboxAgentFile);

  log.info("sandbox.prepare.done", {
    sandboxConfigFile: layout.sandboxConfigFile,
    sandboxPluginFiles,
    sandboxAgentFile,
  });

  return { layout, sandboxPluginFiles, sandboxAgentFile };
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

function requiredOption(value: string | undefined, name: string): string {
  if (!value) {
    throw new Error(`${name} is required`);
  }

  return value;
}

export function createCli(io: CliIO = defaultIO, deps: RunDeps = {}) {
  const cli = cac("cli-v2");

  cli.command(Command.Hello, "Print hello world").action(() => {
    io.stdout.write("hello world\n");
    return 0;
  });

  // cli
  //   .command(
  //     Command.SingleAgent,
  //     "Run one explicit agent in an isolated OpenCode sandbox",
  //   )
  //   .option("--orig <path>", "Source OpenCode config root")
  //   .option("--dest <path>", "Sandbox destination directory")
  //   .option(
  //     "--config <path>",
  //     "Source OpenCode config file, relative to --orig unless absolute",
  //   )
  //   .option(
  //     "--plugin-dir <path>",
  //     "Source local plugin dir, relative to --orig unless absolute",
  //   )
  //   .option("--agent <name>", "OpenCode agent name to run")
  //   .option(
  //     "--agent-file <path>",
  //     "Source agent file, relative to --orig unless absolute",
  //   )
  //   .option("--prompt <text>", "Prompt/message passed to opencode run")
  //   .action(
  //     async (options: {
  //       orig?: Path;
  //       dest?: Path;
  //       config?: Path;
  //       plugin?: Path;
  //       agent?: string;
  //       agentFile?: Path;
  //       prompt?: string;
  //     }) => {
  //       const sourceRoot = path.resolve(options.orig ?? currentPackageRoot());
  //       const sandboxRoot = path.resolve(
  //         options.dest ??
  //           // ToDo: What happens if the path already exists?
  //           (await mkdtemp(path.join(os.tmpdir(), "opencode-cli-v2-"))),
  //       );
  //
  //       const sourceFiles = resolveSourceFiles(sourceRoot, {
  //         config: options.config,
  //         plugin: options.plugin,
  //         agentFile: requiredOption(options.agentFile, "--agent-file"),
  //       });
  //       const spec: SingleAgentSandboxSpec = {
  //         sourceRoot,
  //         sandboxRoot,
  //         agentName: requiredOption(options.agent, "--agent"),
  //         prompt: requiredOption(options.prompt, "--prompt"),
  //         ...sourceFiles,
  //       };
  //       const prepared = await prepareSingleAgentSandbox(spec);
  //
  //       return runSingleAgentInSandbox(
  //         {
  //           layout: prepared.layout,
  //           agentName: spec.agentName,
  //           prompt: spec.prompt,
  //         },
  //         io,
  //         deps,
  //       );
  //     },
  //   );

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
  logger = createLogger();
  const cli = createCli(io, deps);

  try {
    console.info = (message?: unknown) => {
      io.stdout.write(`${message ?? ""}\n`);
    };

    // Only parse, do not run when doing run: false
    const parsed = cli.parse(argv, { run: false });

    if (parsed.options.help) {
      return 0;
    }

    if (!cli.matchedCommand && parsed.args.length > 0) {
      io.stderr.write(`Unknown command: ${parsed.args.join(" ")}\n`);
      cli.outputHelp();
      return 1;
    }

    if (!cli.matchedCommand) {
      io.stderr.write("No command provided.");
      cli.outputHelp();
      return 1;
    }

    const result = await cli.runMatchedCommand();
    return typeof result === "number" ? result : 0;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const stack = error instanceof Error ? error.stack : undefined;
    logger.error("cli.error", { message, stack });
    io.stderr.write(`${stack ?? message}\n`);
    return 1;
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
