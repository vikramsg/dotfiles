import { spawn } from "node:child_process";
import { chmod, mkdir, mkdtemp, readdir, readFile, stat, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  createSingleAgentSandboxLayout,
  prepareSingleAgentSandbox,
  runCli,
} from "./index.ts";

const opencodeRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

type CapturedIO = {
  stdout: string;
  stderr: string;
  io: {
    stdout: { write(text: string): void };
    stderr: { write(text: string): void };
  };
};

async function tempDir(name = "cli-v2-test-") {
  return mkdtemp(path.join(os.tmpdir(), name));
}

function captureIO(): CapturedIO {
  const captured = {
    stdout: "",
    stderr: "",
    io: {
      stdout: {
        write(text: string) {
          captured.stdout += text;
        },
      },
      stderr: {
        write(text: string) {
          captured.stderr += text;
        },
      },
    },
  };

  return captured;
}

async function writeSourceFiles(root: string) {
  const config = path.join(root, "opencode.json");
  const pluginA = path.join(root, "plugins", "orchestration-state.js");
  const pluginB = path.join(root, "plugins", "stop-marker.js");
  const ignoredPlugin = path.join(root, "plugins", "ignored.ts");
  const agent = path.join(root, "agents", "hello-world.md");
  const auth = path.join(root, "auth.json");
  const configText = JSON.stringify(
    {
      plugin: ["opencode-websearch-cited@1.2.0", "./plugins/orchestration-state.js"],
    },
    null,
    2,
  );

  await mkdir(path.dirname(pluginA), { recursive: true });
  await mkdir(path.dirname(agent), { recursive: true });

  await writeFile(config, configText);
  await writeFile(pluginA, "export const pluginA = true\n");
  await writeFile(pluginB, "export const pluginB = true\n");
  await writeFile(ignoredPlugin, "export const ignored = true\n");
  await writeFile(agent, "---\ndescription: hello world\n---\n\nSay hello world.\n");
  await writeFile(auth, '{"auth":true}\n');

  return {
    sourceConfigFile: config,
    pluginA,
    pluginB,
    ignoredPlugin,
    sourceAgentFile: agent,
    sourceAuthFile: auth,
    configText,
  };
}

async function withHomeAuth<T>(fn: (home: string, authFile: string) => Promise<T>): Promise<T> {
  const originalHome = process.env.HOME;
  const home = await tempDir("cli-v2-home-");
  const authFile = path.join(home, ".local", "share", "opencode", "auth.json");

  await mkdir(path.dirname(authFile), { recursive: true });
  await writeFile(authFile, '{"auth":true}\n');

  process.env.HOME = home;
  try {
    return await fn(home, authFile);
  } finally {
    if (originalHome === undefined) {
      delete process.env.HOME;
    } else {
      process.env.HOME = originalHome;
    }
  }
}

async function writeScenarioRecipe(root: string, recipe: Record<string, unknown> = {}) {
  const scenarioDir = path.join(root, "scenario");

  await mkdir(scenarioDir, { recursive: true });
  await writeFile(path.join(scenarioDir, "prompt.md"), "Scenario prompt\n");
  await writeFile(
    path.join(scenarioDir, "scenario.json"),
    JSON.stringify(
      {
        name: "custom-scenario",
        agent: "hello-world",
        agentFile: "fixtures/agents/hello-world.md",
        promptFile: "prompt.md",
        ...recipe,
      },
      null,
      2,
    ),
  );

  return scenarioDir;
}

async function makeFakeOpencode(bin: string, recordPath: string, exitCode = 0) {
  const fakeOpencode = path.join(bin, "opencode");
  await mkdir(bin, { recursive: true });
  await writeFile(
    fakeOpencode,
    `#!/usr/bin/env node
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
const args = process.argv.slice(2);
const configDir = path.join(process.env.XDG_CONFIG_HOME, "opencode");
const config = JSON.parse(readFileSync(path.join(configDir, "opencode.json"), "utf8"));
for (const entry of config.plugin ?? []) {
  if (typeof entry === "string" && (entry.startsWith("./") || entry.startsWith("../") || entry.startsWith("plugins/"))) {
    if (!existsSync(path.resolve(configDir, entry))) process.exit(43);
  }
}
writeFileSync(${JSON.stringify(recordPath)}, JSON.stringify({ args, env: process.env, cwd: process.cwd() }, null, 2));
process.stdout.write("fake stdout\\n");
process.stderr.write("fake stderr\\n");
process.exit(${exitCode});
`,
  );
  await chmod(fakeOpencode, 0o755);

  return fakeOpencode;
}

async function readArtifactFiles(sandboxRoot: string) {
  const output = path.join(path.resolve(sandboxRoot), "output");

  return {
    command: await readFile(path.join(output, "command.txt"), "utf8"),
    metadata: JSON.parse(await readFile(path.join(output, "metadata.json"), "utf8")),
    stdout: await readFile(path.join(output, "stdout.txt"), "utf8"),
    stderr: await readFile(path.join(output, "stderr.txt"), "utf8"),
    rawStatus: await readFile(path.join(output, "opencode-exit-status.txt"), "utf8"),
    status: await readFile(path.join(output, "exit-status.txt"), "utf8"),
  };
}

describe("cli-v2", () => {
  it("creates the sandbox directory layout with typed paths", async () => {
    const dest = await tempDir("cli-v2-sandbox-");

    const layout = await createSingleAgentSandboxLayout({ sandboxRoot: dest });

    expect(layout.sandboxRoot).toBe(path.resolve(dest));
    expect(layout.opencodeConfigDir).toBe(path.join(layout.configHome, "opencode"));
    expect(layout.pluginDir).toBe(path.join(layout.opencodeConfigDir, "plugins"));
    expect(layout.agentDir).toBe(path.join(layout.opencodeConfigDir, "agents"));
    expect(layout.worktree).toBe(path.join(layout.sandboxRoot, "worktree"));
    expect(layout.output).toBe(path.join(layout.sandboxRoot, "output"));
    expect(layout.sandboxAuthFile).toBe(path.join(layout.dataHome, "opencode", "auth.json"));

    await writeFile(path.join(layout.pluginDir, ".keep"), "");
    await writeFile(path.join(layout.agentDir, ".keep"), "");
    await writeFile(path.join(layout.dataHome, ".keep"), "");
    await writeFile(path.join(layout.cacheHome, ".keep"), "");
    await writeFile(path.join(layout.stateHome, ".keep"), "");
    await writeFile(path.join(layout.worktree, ".keep"), "");
    await writeFile(path.join(layout.output, ".keep"), "");
  });

  it("prepares a single-agent sandbox from real source files", async () => {
    const orig = await tempDir();
    const dest = await tempDir("cli-v2-sandbox-");
    const files = await writeSourceFiles(orig);

    const prepared = await prepareSingleAgentSandbox({
      sourceRoot: orig,
      sandboxRoot: dest,
      agentName: "custom-agent",
      prompt: "Use the custom agent.",
      sourceConfigFile: files.sourceConfigFile,
      sourceAgentFile: files.sourceAgentFile,
      sourceAuthFile: files.sourceAuthFile,
    });

    const pluginFile = path.join(prepared.layout.pluginDir, "orchestration-state.js");
    const agentFile = path.join(prepared.layout.agentDir, "custom-agent.md");

    expect(prepared.sandboxPluginFiles).toEqual([pluginFile]);
    expect(prepared.sandboxAgentFile).toBe(agentFile);
    expect(await readFile(prepared.layout.sandboxConfigFile, "utf8")).toBe(files.configText);
    expect(await readFile(prepared.layout.sandboxAuthFile, "utf8")).toBe(await readFile(files.sourceAuthFile, "utf8"));
    expect(await readFile(pluginFile, "utf8")).toBe(await readFile(files.pluginA, "utf8"));
    await expect(readFile(path.join(prepared.layout.pluginDir, "stop-marker.js"), "utf8")).rejects.toThrow();
    await expect(readFile(path.join(prepared.layout.pluginDir, "ignored.ts"), "utf8")).rejects.toThrow();
    expect(await readFile(agentFile, "utf8")).toBe(await readFile(files.sourceAgentFile, "utf8"));
  });

  it.each(["../evil", "evil/name", "evil\\name", "", "..", "evil name", "evil.name", "evil$name"])(
    "rejects unsafe agent name %j before preparing files",
    async (agentName) => {
      const orig = await tempDir();
      const dest = await tempDir("cli-v2-sandbox-");
      const files = await writeSourceFiles(orig);

      await expect(
        prepareSingleAgentSandbox({
          sourceRoot: orig,
          sandboxRoot: dest,
          agentName,
          prompt: "Use the custom agent.",
          sourceConfigFile: files.sourceConfigFile,
          sourceAgentFile: files.sourceAgentFile,
          sourceAuthFile: files.sourceAuthFile,
        }),
      ).rejects.toThrow(`Invalid agent name: ${agentName}`);

      await expect(readFile(path.join(dest, "config", "opencode", "agents", "evil.md"), "utf8")).rejects.toThrow();
    },
  );

  it("rejects absolute local plugin paths before copying sandbox files", async () => {
    const orig = await tempDir();
    const dest = await tempDir("cli-v2-sandbox-");
    const config = path.join(orig, "opencode.json");
    const plugin = path.join(orig, "plugins", "absolute.js");
    const agent = path.join(orig, "agents", "hello-world.md");

    await mkdir(path.dirname(plugin), { recursive: true });
    await mkdir(path.dirname(agent), { recursive: true });
    await writeFile(config, JSON.stringify({ plugin }, null, 2));
    await writeFile(plugin, "export const absolute = true\n");
    await writeFile(agent, "absolute plugin test agent\n");

    await expect(
      prepareSingleAgentSandbox({
        sourceRoot: orig,
        sandboxRoot: dest,
        agentName: "custom-agent",
        prompt: "Use the custom agent.",
        sourceConfigFile: config,
        sourceAgentFile: agent,
        sourceAuthFile: path.join(orig, "auth.json"),
      }),
    ).rejects.toThrow(`Absolute local plugin paths are not supported in sandbox config: ${plugin}`);

    const sandboxRoot = path.resolve(dest);
    await expect(readFile(path.join(sandboxRoot, "config", "opencode", "opencode.json"), "utf8")).rejects.toThrow();
    await expect(readFile(path.join(sandboxRoot, "config", "opencode", "plugins", "absolute.js"), "utf8")).rejects.toThrow();
    await expect(readFile(path.join(sandboxRoot, "config", "opencode", "agents", "custom-agent.md"), "utf8")).rejects.toThrow();
  });

  it("rejects traversal plugin entries before copying any plugin files", async () => {
    const parent = await tempDir("cli-v2-source-parent-");
    const orig = path.join(parent, "source");
    const dest = await tempDir("cli-v2-sandbox-");
    const config = path.join(orig, "opencode.json");
    const safePlugin = path.join(orig, "plugins", "local.js");
    const evilPlugin = path.join(parent, "evil.js");
    const agent = path.join(orig, "agents", "hello-world.md");

    await mkdir(path.dirname(safePlugin), { recursive: true });
    await mkdir(path.dirname(agent), { recursive: true });
    await writeFile(config, JSON.stringify({ plugin: ["./plugins/local.js", "../evil.js"] }, null, 2));
    await writeFile(safePlugin, "export const local = true\n");
    await writeFile(evilPlugin, "export const evil = true\n");
    await writeFile(agent, "traversal plugin test agent\n");

    await expect(
      prepareSingleAgentSandbox({
        sourceRoot: orig,
        sandboxRoot: dest,
        agentName: "custom-agent",
        prompt: "Use the custom agent.",
        sourceConfigFile: config,
        sourceAgentFile: agent,
        sourceAuthFile: path.join(orig, "auth.json"),
      }),
    ).rejects.toThrow("Configured local plugin escapes sandbox plugin directory: ../evil.js ->");

    const sandboxRoot = path.resolve(dest);
    await expect(readFile(path.join(sandboxRoot, "config", "evil.js"), "utf8")).rejects.toThrow();
    await expect(readFile(path.join(sandboxRoot, "config", "opencode", "plugins", "local.js"), "utf8")).rejects.toThrow();
  });

  it("runs the hello command through cac", async () => {
    const captured = captureIO();

    const status = await runCli(["node", "cli-v2", "hello"], captured.io);

    expect(status).toBe(0);
    expect(captured.stdout).toBe("hello world\n");
    expect(captured.stderr).toBe("");
  });

  it("runs directly from TypeScript source with Node", async () => {
    const child = spawn(process.execPath, ["sandbox/cli-v2/index.ts", "hello"], {
      cwd: opencodeRoot,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";

    child.stdout?.on("data", (chunk: Buffer) => {
      stdout += chunk.toString();
    });
    child.stderr?.on("data", (chunk: Buffer) => {
      stderr += chunk.toString();
    });

    const status = await new Promise<number | null>((resolve) => {
      child.on("close", (code) => resolve(code));
    });

    expect(status).toBe(0);
    expect(stdout).toBe("hello world\n");
    expect(stderr).toBe("");
  });

  it("runs a generic single-agent sandbox with prompt text and output artifacts", async () => {
    const orig = await tempDir();
    const dest = await tempDir("cli-v2-sandbox-");
    const bin = await tempDir("cli-v2-bin-");
    const files = await writeSourceFiles(orig);
    const prompt = "Use the custom agent.";
    const recordPath = path.join(dest, "opencode-record.json");
    const captured = captureIO();

    await makeFakeOpencode(bin, recordPath);

    const status = await withHomeAuth(() =>
      runCli(
        [
          "node",
          "cli-v2",
          "single-agent",
          "--orig",
          orig,
          "--dest",
          dest,
          "--agent",
          "custom-agent",
          "--agent-file",
          files.sourceAgentFile,
          "--prompt",
          prompt,
        ],
        captured.io,
        { env: { ...process.env, PATH: `${bin}${path.delimiter}${process.env.PATH ?? ""}` } },
      ),
    );

    const record = JSON.parse(await readFile(recordPath, "utf8"));
    const sandboxRoot = path.resolve(dest);
    const artifacts = await readArtifactFiles(dest);

    expect(status).toBe(0);
    expect(record.args).toEqual(["run", "--dir", path.join(sandboxRoot, "worktree"), "--agent", "custom-agent", prompt]);
    expect(record.env.XDG_CONFIG_HOME).toBe(path.join(sandboxRoot, "config"));
    expect(record.env.XDG_DATA_HOME).toBe(path.join(sandboxRoot, "data"));
    expect(record.env.XDG_CACHE_HOME).toBe(path.join(sandboxRoot, "cache"));
    expect(record.env.XDG_STATE_HOME).toBe(path.join(sandboxRoot, "state"));
    expect(await readFile(path.join(sandboxRoot, "config", "opencode", "opencode.json"), "utf8")).toBe(files.configText);
    expect((await readdir(path.join(sandboxRoot, "config", "opencode", "plugins"))).sort()).toEqual(["orchestration-state.js"]);
    expect(await readFile(path.join(sandboxRoot, "config", "opencode", "agents", "custom-agent.md"), "utf8")).toBe(
      await readFile(files.sourceAgentFile, "utf8"),
    );
    expect(captured.stdout).toBe("fake stdout\n");
    expect(captured.stderr).toBe("fake stderr\n");
    expect(artifacts.stdout).toBe("fake stdout\n");
    expect(artifacts.stderr).toBe("fake stderr\n");
    expect(artifacts.rawStatus).toBe("0\n");
    expect(artifacts.status).toBe("0\n");
    expect(artifacts.command).toContain("opencode run --dir");
    expect(artifacts.metadata.agentName).toBe("custom-agent");
    expect(artifacts.metadata.promptSource).toBe("text");
  });

  it("reads single-agent prompt text from a file", async () => {
    const orig = await tempDir();
    const dest = await tempDir("cli-v2-sandbox-");
    const bin = await tempDir("cli-v2-bin-");
    const files = await writeSourceFiles(orig);
    const promptFile = path.join(orig, "prompt.md");
    const prompt = "Use this file prompt.\n";
    const recordPath = path.join(dest, "opencode-record.json");
    const captured = captureIO();

    await writeFile(promptFile, prompt);
    await makeFakeOpencode(bin, recordPath);

    const status = await withHomeAuth(() =>
      runCli(
        [
          "node",
          "cli-v2",
          "single-agent",
          "--orig",
          orig,
          "--dest",
          dest,
          "--agent",
          "custom-agent",
          "--agent-file",
          files.sourceAgentFile,
          "--prompt-file",
          promptFile,
        ],
        captured.io,
        { env: { ...process.env, PATH: `${bin}${path.delimiter}${process.env.PATH ?? ""}` } },
      ),
    );

    const record = JSON.parse(await readFile(recordPath, "utf8"));
    const artifacts = await readArtifactFiles(dest);

    expect(status).toBe(0);
    expect(record.args.at(-1)).toBe(prompt);
    expect(artifacts.metadata.promptSource).toBe("file");
    expect(artifacts.metadata.promptFile).toBe(path.resolve(promptFile));
  });

  it.each([
    ["both", ["--prompt", "hello", "--prompt-file", "prompt.md"]],
    ["neither", []],
  ])("requires exactly one prompt source for %s prompt options", async (_name, promptArgs) => {
    const orig = await tempDir();
    const dest = await tempDir("cli-v2-sandbox-");
    const files = await writeSourceFiles(orig);
    const captured = captureIO();

    await writeFile(path.join(orig, "prompt.md"), "hello from file");

    const status = await runCli(
      [
        "node",
        "cli-v2",
        "single-agent",
        "--orig",
        orig,
        "--dest",
        dest,
        "--agent",
        "custom-agent",
        "--agent-file",
        files.sourceAgentFile,
        ...promptArgs,
      ],
      captured.io,
    );

    expect(status).toBe(1);
    expect(captured.stderr).toBe("Use exactly one of --prompt or --prompt-file\n");
    await expect(readFile(path.join(path.resolve(dest), "config", "opencode", "opencode.json"), "utf8")).rejects.toThrow();
  });

  it("runs hello-world using the self-contained fixture agent", async () => {
    const dest = await tempDir("cli-v2-sandbox-");
    const bin = await tempDir("cli-v2-bin-");
    const recordPath = path.join(dest, "opencode-record.json");
    const fixtureAgent = path.join(opencodeRoot, "sandbox", "cli-v2", "fixtures", "agents", "hello-world.md");
    const captured = captureIO();

    await makeFakeOpencode(bin, recordPath);

    const status = await withHomeAuth(() =>
      runCli(
        ["node", "cli-v2", "hello-world", "--dest", dest],
        captured.io,
        { env: { ...process.env, PATH: `${bin}${path.delimiter}${process.env.PATH ?? ""}` } },
      ),
    );

    const record = JSON.parse(await readFile(recordPath, "utf8"));
    const sandboxRoot = path.resolve(dest);

    expect(status).toBe(0);
    expect(record.args).toEqual(["run", "--dir", path.join(sandboxRoot, "worktree"), "--agent", "hello-world", "Respond with hello world."]);
    expect(await readFile(path.join(sandboxRoot, "config", "opencode", "agents", "hello-world.md"), "utf8")).toBe(
      await readFile(fixtureAgent, "utf8"),
    );
  });

  it("runs a scenario recipe and copies the fixture worktree", async () => {
    const dest = await tempDir("cli-v2-sandbox-");
    const bin = await tempDir("cli-v2-bin-");
    const scenarioDir = path.join(opencodeRoot, "sandbox", "cli-v2", "scenarios", "hello-world");
    const recordPath = path.join(dest, "opencode-record.json");
    const captured = captureIO();

    await makeFakeOpencode(bin, recordPath);

    const status = await withHomeAuth(() =>
      runCli(
        ["node", "cli-v2", "scenario", scenarioDir, "--dest", dest],
        captured.io,
        { env: { ...process.env, PATH: `${bin}${path.delimiter}${process.env.PATH ?? ""}` } },
      ),
    );

    const record = JSON.parse(await readFile(recordPath, "utf8"));
    const sandboxRoot = path.resolve(dest);
    const artifacts = await readArtifactFiles(dest);

    expect(status).toBe(0);
    expect(record.args).toEqual([
      "run",
      "--dir",
      path.join(sandboxRoot, "worktree"),
      "--agent",
      "hello-world",
      await readFile(path.join(scenarioDir, "prompt.md"), "utf8"),
    ]);
    expect(await readFile(path.join(sandboxRoot, "worktree", "README.md"), "utf8")).toBe(
      await readFile(path.join(scenarioDir, "worktree", "README.md"), "utf8"),
    );
    expect(await readFile(path.join(sandboxRoot, "config", "opencode", "agents", "hello-world.md"), "utf8")).toBe(
      await readFile(path.join(opencodeRoot, "sandbox", "cli-v2", "fixtures", "agents", "hello-world.md"), "utf8"),
    );
    expect(artifacts.metadata.command).toBe("scenario");
    expect(artifacts.metadata.scenarioName).toBe("hello-world");
  });

  it("rejects invalid scenario timeout before creating the destination sandbox", async () => {
    const root = await tempDir();
    const scenarioDir = path.join(opencodeRoot, "sandbox", "cli-v2", "scenarios", "hello-world");
    const dest = path.join(root, "dest-that-should-not-be-created");
    const captured = captureIO();

    const status = await runCli(
      ["node", "cli-v2", "scenario", scenarioDir, "--dest", dest, "--timeout-ms", "not-a-number"],
      captured.io,
    );

    expect(status).toBe(1);
    expect(captured.stderr).toBe("--timeout-ms must be a positive integer\n");
    await expect(stat(dest)).rejects.toThrow();
  });

  it("fails cleanly before sandbox creation when a scenario agent file is missing", async () => {
    const root = await tempDir();
    const missingAgentPath = path.join(opencodeRoot, "sandbox", "cli-v2", "fixtures", "agents", "missing-agent-for-preflight.md");
    const scenarioDir = await writeScenarioRecipe(root, {
      agentFile: "fixtures/agents/missing-agent-for-preflight.md",
    });
    const dest = path.join(root, "dest-that-should-not-be-created");
    const child = spawn(process.execPath, ["sandbox/cli-v2/index.ts", "scenario", scenarioDir, "--dest", dest], {
      cwd: opencodeRoot,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";

    child.stdout?.on("data", (chunk: Buffer) => {
      stdout += chunk.toString();
    });
    child.stderr?.on("data", (chunk: Buffer) => {
      stderr += chunk.toString();
    });

    const status = await new Promise<number | null>((resolve) => {
      child.on("close", (code) => resolve(code));
    });

    expect(status).toBe(1);
    expect(stdout).toBe("");
    expect(stderr).toBe(`Source agent file does not exist: ${missingAgentPath}\n`);
    await expect(stat(dest)).rejects.toThrow();
  });

  it.each([
    ["absolute fixtureDir", (root: string) => path.join(root, "outside-worktree"), "Scenario fixtureDir must be relative"],
    ["traversal fixtureDir", () => "../outside-worktree", "Scenario fixtureDir escapes scenario directory"],
  ])("fails cleanly before sandbox preparation for %s", async (_name, fixtureDir, message) => {
    const root = await tempDir();
    const scenarioDir = await writeScenarioRecipe(root, { fixtureDir: fixtureDir(root) });
    const dest = path.join(root, "dest-that-should-not-be-created");
    const captured = captureIO();

    await mkdir(path.join(root, "outside-worktree"), { recursive: true });

    const status = await runCli(["node", "cli-v2", "scenario", scenarioDir, "--dest", dest], captured.io);

    expect(status).toBe(1);
    expect(captured.stderr).toContain("Scenario");
    expect(captured.stderr).toContain(message);
    await expect(stat(dest)).rejects.toThrow();
  });

  it("fails cleanly before explicit destination creation when a scenario fixture contains a symlink", async () => {
    const root = await tempDir();
    const scenarioDir = await writeScenarioRecipe(root, { fixtureDir: "worktree" });
    const fixtureDir = path.join(scenarioDir, "worktree");
    const outsideFixtureFile = path.join(root, "outside-fixture.txt");
    const fixtureLink = path.join(fixtureDir, "outside-fixture-link.txt");
    const dest = path.join(root, "dest-that-should-not-be-created");
    const captured = captureIO();

    await mkdir(fixtureDir, { recursive: true });
    await writeFile(outsideFixtureFile, "outside fixture\n");
    await symlink(outsideFixtureFile, fixtureLink);

    const status = await runCli(["node", "cli-v2", "scenario", scenarioDir, "--dest", dest], captured.io);

    expect(status).toBe(1);
    expect(captured.stderr).toBe(`Scenario fixture contains symlink: ${fixtureLink}\n`);
    await expect(stat(dest)).rejects.toThrow();
  });

  it("returns timeout status when opencode exceeds the CLI timeout", async () => {
    const orig = await tempDir();
    const dest = await tempDir("cli-v2-sandbox-");
    const bin = await tempDir("cli-v2-bin-");
    const files = await writeSourceFiles(orig);
    const captured = captureIO();
    const fakeOpencode = path.join(bin, "opencode");

    await mkdir(bin, { recursive: true });
    await writeFile(fakeOpencode, "#!/usr/bin/env node\nsetTimeout(() => {}, 10000);\n");
    await chmod(fakeOpencode, 0o755);

    const status = await withHomeAuth(() =>
      runCli(
        [
          "node",
          "cli-v2",
          "single-agent",
          "--orig",
          orig,
          "--dest",
          dest,
          "--agent",
          "custom-agent",
          "--agent-file",
          files.sourceAgentFile,
          "--prompt",
          "hello",
          "--timeout-ms",
          "50",
        ],
        captured.io,
        { env: { ...process.env, PATH: `${bin}${path.delimiter}${process.env.PATH ?? ""}` } },
      ),
    );

    const artifacts = await readArtifactFiles(dest);

    expect(status).toBe(124);
    expect(captured.stderr).toContain("opencode timed out after 50ms");
    expect(artifacts.rawStatus).toBe("124\n");
    expect(artifacts.status).toBe("124\n");
  });

  it("returns a clean failure when opencode is missing", async () => {
    const orig = await tempDir();
    const dest = await tempDir("cli-v2-sandbox-");
    const files = await writeSourceFiles(orig);
    const captured = captureIO();

    const status = await withHomeAuth(() =>
      runCli(
        [
          "node",
          "cli-v2",
          "single-agent",
          "--orig",
          orig,
          "--dest",
          dest,
          "--agent",
          "custom-agent",
          "--agent-file",
          files.sourceAgentFile,
          "--prompt",
          "Hello from missing CLI test.",
        ],
        captured.io,
        { env: { PATH: "" } },
      ),
    );

    expect(status).toBe(127);
    expect(captured.stderr).toContain("opencode CLI was not found");
    expect((await readArtifactFiles(dest)).status).toBe("127\n");
  });

  it("does not advertise or run unsupported commands", async () => {
    const captured = captureIO();

    const helpStatus = await runCli(["node", "cli-v2", "--help"], captured.io);
    const unknownStatus = await runCli(["node", "cli-v2", "removed-command"], captured.io);

    expect(helpStatus).toBe(0);
    expect(captured.stdout).toContain("hello-world");
    expect(captured.stdout).toContain("scenario");
    expect(captured.stdout).not.toContain("removed-command");
    expect(unknownStatus).toBe(1);
    expect(captured.stderr).toContain("Unknown command: removed-command");
  });

  it("uses only the agreed sandbox Makefile targets", async () => {
    const makefile = await readFile(path.join(opencodeRoot, "sandbox", "Makefile"), "utf8");
    const targets = Array.from(makefile.matchAll(/^([A-Za-z0-9_-]+):/gm), (match) => match[1]);

    expect(targets).toEqual(["check", "test", "hello", "hello-world", "single-agent", "scenario"]);
    expect(makefile).not.toMatch(/^build:/m);
    expect(makefile).toContain("npm --prefix .. run check:sandbox:v2");
    expect(makefile).toContain("$(abspath $(SCENARIO))");
  });

  it("uses source-run package scripts without a CLI v2 build surface", async () => {
    const packageJson = JSON.parse(await readFile(path.join(opencodeRoot, "package.json"), "utf8"));
    const scripts = packageJson.scripts as Record<string, string>;

    expect(scripts["check:sandbox:v2"]).toBe("tsc -p sandbox/cli-v2/tsconfig.json");
    expect(scripts["sandbox:v2"]).toBe("node sandbox/cli-v2/index.ts");
    expect(scripts["test:sandbox:v2"]).toBe("vitest run sandbox/cli-v2");
    expect(scripts.build).toContain("npm run check:sandbox:v2");
    expect(scripts).not.toHaveProperty("build:sandbox:v2");
    expect(scripts).not.toHaveProperty("typecheck:sandbox:v2");
  });

  it("checks CLI v2 TypeScript without emitting build output", async () => {
    const tsconfig = JSON.parse(await readFile(path.join(opencodeRoot, "sandbox", "cli-v2", "tsconfig.json"), "utf8"));
    const options = tsconfig.compilerOptions as Record<string, unknown>;

    expect(options.noEmit).toBe(true);
    expect(options.allowImportingTsExtensions).toBe(true);
    expect(options).not.toHaveProperty("outDir");
    expect(options).not.toHaveProperty("rootDir");
    expect(options).not.toHaveProperty("sourceMap");
  });

  it("ships the checked-in hello-world scenario", async () => {
    const scenarioDir = path.join(opencodeRoot, "sandbox", "cli-v2", "scenarios", "hello-world");
    const scenarioText = await readFile(path.join(scenarioDir, "scenario.json"), "utf8");
    const scenario = JSON.parse(scenarioText);

    expect(scenario).toEqual({
      name: "hello-world",
      agent: "hello-world",
      agentFile: "fixtures/agents/hello-world.md",
      promptFile: "prompt.md",
      fixtureDir: "worktree",
    });
    await expect(stat(path.join(scenarioDir, "prompt.md"))).resolves.toMatchObject({});
    await expect(stat(path.join(scenarioDir, "worktree", "README.md"))).resolves.toMatchObject({});
  });

  it("keeps specs contract-first with the required sections", async () => {
    for (const fileName of ["single-agent.md", "scenario.md"]) {
      const text = await readFile(path.join(opencodeRoot, "sandbox", "cli-v2", "docs", "specs", fileName), "utf8");

      expect(text.startsWith(`# ${fileName === "single-agent.md" ? "Single Agent" : "Scenario"}\n`)).toBe(true);
      expect(text).toContain("```text");
      for (const heading of ["Contracts", "Flow", "Inputs", "Outputs", "Lifecycle", "Errors", "Non-Goals", "Implementation Notes"]) {
        expect(text).toContain(`## ${heading}`);
      }
    }
  });

  it("records the implementation plan version", async () => {
    const notes = await readFile(path.join(opencodeRoot, "sandbox", "cli-v2", "implementation_notes.md"), "utf8");

    expect(notes).toContain("### PLAN VERSION: 1");
    expect(notes).toContain("### PLAN VERSION: 2");
    expect(notes).toContain("### PLAN VERSION: 4");
  });
});
