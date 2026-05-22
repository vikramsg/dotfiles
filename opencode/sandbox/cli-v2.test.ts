import { chmod, mkdir, mkdtemp, readdir, readFile, writeFile } from "node:fs/promises"
import os from "node:os"
import path from "node:path"
import { describe, expect, it } from "vitest"
import {
  createSingleAgentSandboxLayout,
  prepareSingleAgentSandbox,
  runCli,
} from "./cli-v2.js"

async function tempDir(name = "cli-v2-test-") {
  return mkdtemp(path.join(os.tmpdir(), name))
}

async function writeSourceFiles(root: string) {
  const config = path.join(root, "opencode.json")
  const pluginA = path.join(root, "plugins", "orchestration-state.js")
  const pluginB = path.join(root, "plugins", "stop-marker.js")
  const ignoredPlugin = path.join(root, "plugins", "ignored.ts")
  const agent = path.join(root, "agents", "hello-world.md")
  const configText = JSON.stringify(
    {
      plugin: ["opencode-websearch-cited@1.2.0", "./plugins/orchestration-state.js"],
    },
    null,
    2,
  )

  await mkdir(path.dirname(pluginA), { recursive: true })
  await mkdir(path.dirname(agent), { recursive: true })

  await writeFile(config, configText)
  await writeFile(pluginA, "export const pluginA = true\n")
  await writeFile(pluginB, "export const pluginB = true\n")
  await writeFile(ignoredPlugin, "export const ignored = true\n")
  await writeFile(agent, "---\ndescription: hello world\n---\n\nSay hello world.\n")

  return {
    sourceConfigFile: config,
    pluginA,
    pluginB,
    ignoredPlugin,
    sourceAgentFile: agent,
    configText,
  }
}

async function writeScenarioSource(root: string, scenarioRoot: string, options?: { scriptedSubagents?: Record<string, string[]>, assertions?: unknown[] }) {
  await mkdir(path.join(root, "agents"), { recursive: true })
  await mkdir(path.join(scenarioRoot, "worktree"), { recursive: true })
  await writeFile(path.join(root, "opencode.json"), JSON.stringify({ plugin: [] }, null, 2))
  await writeFile(path.join(root, "agents", "orchestrator.md"), "orchestrator\n")
  await writeFile(path.join(root, "agents", "planner.md"), "planner\n")
  await writeFile(path.join(root, "agents", "reviewer.md"), "reviewer\n")
  await writeFile(path.join(scenarioRoot, "request.md"), "Do work.\n")
  await writeFile(path.join(scenarioRoot, "expected.json"), JSON.stringify({ assertions: options?.assertions ?? [] }, null, 2))
  await writeFile(
    path.join(scenarioRoot, "scenario.json"),
    JSON.stringify(
      {
        name: "plugin-scenario",
        primaryAgent: "orchestrator",
        agents: { orchestrator: "agents/orchestrator.md", planner: "agents/planner.md", reviewer: "agents/reviewer.md" },
        promptFile: "request.md",
        fixtureDir: "worktree",
        expectedFile: "expected.json",
        scriptedSubagents: options?.scriptedSubagents,
      },
      null,
      2,
    ),
  )
}

async function writePluginDrivingOpencode(bin: string, calls: string) {
  const fakeOpencode = path.join(bin, "opencode")
  await writeFile(
    fakeOpencode,
    `#!/usr/bin/env node
import { readFileSync } from "node:fs"
import path from "node:path"
import { pathToFileURL } from "node:url"
const configDir = path.join(process.env.XDG_CONFIG_HOME, "opencode")
const config = JSON.parse(readFileSync(path.join(configDir, "opencode.json"), "utf8"))
const pluginEntry = config.plugin.find((entry) => entry.endsWith("sandbox-task-trace.js"))
const pluginModule = await import(pathToFileURL(path.resolve(configDir, pluginEntry)).href)
const hooks = await pluginModule.SandboxTracePlugin()
${calls}
`,
  )
  await chmod(fakeOpencode, 0o755)
}

describe("cli-v2", () => {
  it("creates the sandbox directory layout with typed paths", async () => {
    const dest = await tempDir("cli-v2-sandbox-")

    const layout = await createSingleAgentSandboxLayout({ sandboxRoot: dest })

    expect(layout.sandboxRoot).toBe(path.resolve(dest))
    expect(layout.opencodeConfigDir).toBe(path.join(layout.configHome, "opencode"))
    expect(layout.pluginDir).toBe(path.join(layout.opencodeConfigDir, "plugins"))
    expect(layout.agentDir).toBe(path.join(layout.opencodeConfigDir, "agents"))
    expect(layout.worktree).toBe(path.join(layout.sandboxRoot, "worktree"))
    expect(layout.output).toBe(path.join(layout.sandboxRoot, "output"))

    await expect(readFile(layout.sandboxConfigFile, "utf8")).rejects.toThrow()
    await writeFile(path.join(layout.pluginDir, ".keep"), "")
    await writeFile(path.join(layout.agentDir, ".keep"), "")
    await writeFile(path.join(layout.dataHome, ".keep"), "")
    await writeFile(path.join(layout.cacheHome, ".keep"), "")
    await writeFile(path.join(layout.stateHome, ".keep"), "")
    await writeFile(path.join(layout.worktree, ".keep"), "")
    await writeFile(path.join(layout.output, ".keep"), "")
  })

  it("prepares a single-agent sandbox from real source files", async () => {
    const orig = await tempDir()
    const dest = await tempDir("cli-v2-sandbox-")
    const files = await writeSourceFiles(orig)

    const prepared = await prepareSingleAgentSandbox({
      sourceRoot: orig,
      sandboxRoot: dest,
      agentName: "custom-agent",
      prompt: "Use the custom agent.",
      sourceConfigFile: files.sourceConfigFile,
      sourceAgentFile: files.sourceAgentFile,
    })

    const expectedPluginFiles = [path.join(prepared.layout.pluginDir, "orchestration-state.js")]
    const expectedAgentFile = path.join(prepared.layout.agentDir, "custom-agent.md")

    expect(prepared.sandboxPluginFiles).toEqual(expectedPluginFiles)
    expect(prepared.sandboxAgentFile).toBe(expectedAgentFile)
    expect(await readFile(prepared.layout.sandboxConfigFile, "utf8")).toBe(files.configText)
    expect(await readFile(expectedPluginFiles[0], "utf8")).toBe(await readFile(files.pluginA, "utf8"))
    await expect(readFile(path.join(prepared.layout.pluginDir, "stop-marker.js"), "utf8")).rejects.toThrow()
    await expect(readFile(path.join(prepared.layout.pluginDir, "ignored.ts"), "utf8")).rejects.toThrow()
    expect(await readFile(expectedAgentFile, "utf8")).toBe(
      await readFile(files.sourceAgentFile, "utf8"),
    )
  })

  it("prepares a single-agent sandbox with a string-form local plugin", async () => {
    const orig = await tempDir()
    const dest = await tempDir("cli-v2-sandbox-")
    const config = path.join(orig, "opencode.json")
    const plugin = path.join(orig, "plugins", "local.js")
    const agent = path.join(orig, "agents", "hello-world.md")
    const configText = JSON.stringify({ plugin: "./plugins/local.js" }, null, 2)
    const pluginText = "export const local = true\n"

    await mkdir(path.dirname(plugin), { recursive: true })
    await mkdir(path.dirname(agent), { recursive: true })
    await writeFile(config, configText)
    await writeFile(plugin, pluginText)
    await writeFile(agent, "string plugin test agent\n")

    const prepared = await prepareSingleAgentSandbox({
      sourceRoot: orig,
      sandboxRoot: dest,
      agentName: "custom-agent",
      prompt: "Use the custom agent.",
      sourceConfigFile: config,
      sourceAgentFile: agent,
    })

    const expectedPluginFile = path.join(prepared.layout.pluginDir, "local.js")
    const expectedAgentFile = path.join(prepared.layout.agentDir, "custom-agent.md")

    expect(await readFile(prepared.layout.sandboxConfigFile, "utf8")).toBe(configText)
    expect(prepared.sandboxPluginFiles).toEqual([expectedPluginFile])
    expect(await readFile(expectedPluginFile, "utf8")).toBe(pluginText)
    expect(prepared.sandboxAgentFile).toBe(expectedAgentFile)
    expect(await readFile(expectedAgentFile, "utf8")).toBe("string plugin test agent\n")
  })

  it("prepares a single-agent sandbox with a bare relative local plugin path", async () => {
    const orig = await tempDir()
    const dest = await tempDir("cli-v2-sandbox-")
    const config = path.join(orig, "opencode.json")
    const plugin = path.join(orig, "plugins", "local.js")
    const agent = path.join(orig, "agents", "hello-world.md")
    const configText = JSON.stringify({ plugin: ["plugins/local.js"] }, null, 2)
    const pluginText = "export const local = true\n"

    await mkdir(path.dirname(plugin), { recursive: true })
    await mkdir(path.dirname(agent), { recursive: true })
    await writeFile(config, configText)
    await writeFile(plugin, pluginText)
    await writeFile(agent, "bare relative plugin test agent\n")

    const prepared = await prepareSingleAgentSandbox({
      sourceRoot: orig,
      sandboxRoot: dest,
      agentName: "custom-agent",
      prompt: "Use the custom agent.",
      sourceConfigFile: config,
      sourceAgentFile: agent,
    })

    const expectedPluginFile = path.join(prepared.layout.pluginDir, "local.js")

    expect(await readFile(prepared.layout.sandboxConfigFile, "utf8")).toBe(configText)
    expect(prepared.sandboxPluginFiles).toEqual([expectedPluginFile])
    expect(await readFile(expectedPluginFile, "utf8")).toBe(pluginText)
  })

  it.each(["../evil", "evil/name", "evil\\name", "", "..", "evil name", "evil.name", "evil$name"])(
    "rejects unsafe agent name %j before preparing files",
    async (agentName) => {
      const orig = await tempDir()
      const dest = await tempDir("cli-v2-sandbox-")
      const files = await writeSourceFiles(orig)

      await expect(
        prepareSingleAgentSandbox({
          sourceRoot: orig,
          sandboxRoot: dest,
          agentName,
          prompt: "Use the custom agent.",
          sourceConfigFile: files.sourceConfigFile,
          sourceAgentFile: files.sourceAgentFile,
        }),
      ).rejects.toThrow(`Invalid agent name: ${agentName}`)

      await expect(readFile(path.join(dest, "config", "opencode", "agents", "evil.md"), "utf8")).rejects.toThrow()
      await expect(readFile(path.join(dest, "config", "opencode", "evil.md"), "utf8")).rejects.toThrow()
    },
  )

  it("fails clearly when config references a missing local plugin", async () => {
    const orig = await tempDir()
    const dest = await tempDir("cli-v2-sandbox-")
    const agent = path.join(orig, "agents", "hello-world.md")
    const missingPlugin = path.join(orig, "plugins", "missing.js")

    await mkdir(path.dirname(agent), { recursive: true })
    await writeFile(path.join(orig, "opencode.json"), JSON.stringify({ plugin: ["./plugins/missing.js"] }))
    await writeFile(agent, "missing plugin test agent\n")

    await expect(
      prepareSingleAgentSandbox({
        sourceRoot: orig,
        sandboxRoot: dest,
        agentName: "custom-agent",
        prompt: "Use the custom agent.",
        sourceConfigFile: path.join(orig, "opencode.json"),
        sourceAgentFile: agent,
      }),
    ).rejects.toThrow(`Configured local plugin does not exist: ./plugins/missing.js -> ${missingPlugin}`)

    await expect(readdir(path.join(path.resolve(dest), "config", "opencode"))).rejects.toThrow()
  })

  it("returns a clean validation error when a local plugin is missing", async () => {
    const orig = await tempDir()
    const dest = await tempDir("cli-v2-sandbox-")
    const agent = path.join(orig, "agents", "test.md")
    const missingPlugin = path.join(orig, "plugins", "missing.js")
    let stderr = ""

    await mkdir(path.dirname(agent), { recursive: true })
    await writeFile(path.join(orig, "opencode.json"), JSON.stringify({ plugin: ["./plugins/missing.js"] }))
    await writeFile(agent, "test agent\n")

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
        "agents/test.md",
        "--prompt",
        "hello",
      ],
      { stdout: { write() {} }, stderr: { write(text) { stderr += text } } },
    )

    expect(status).toBe(1)
    expect(stderr).toBe(`Configured local plugin does not exist: ./plugins/missing.js -> ${missingPlugin}\n`)
    expect(stderr).not.toContain("Error:")
    expect(stderr).not.toContain("at ")
    expect(stderr).not.toContain("cli-v2.ts")
  })

  it("returns a clean validation error when opencode.json is malformed", async () => {
    const orig = await tempDir()
    const dest = await tempDir("cli-v2-sandbox-")
    const agent = path.join(orig, "agents", "test.md")
    let stderr = ""

    await mkdir(path.dirname(agent), { recursive: true })
    await writeFile(path.join(orig, "opencode.json"), "{ invalid json")
    await writeFile(agent, "test agent\n")

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
        "agents/test.md",
        "--prompt",
        "hello",
      ],
      { stdout: { write() {} }, stderr: { write(text) { stderr += text } } },
    )

    expect(status).toBe(1)
    expect(stderr).toBe(
      `Could not parse config file ${path.join(orig, "opencode.json")}\n`,
    )
    expect(stderr).not.toContain("Error:")
    expect(stderr).not.toContain("at ")
    expect(stderr).not.toContain("cli-v2.ts")
  })

  it.each([
    ["invalid plugin item type", ["./plugins/local.js", 123]],
    ["invalid plugin field shape", { path: "./plugins/local.js" }],
  ])("returns a clean validation error for %s", async (_name, plugin) => {
    const orig = await tempDir()
    const dest = await tempDir("cli-v2-sandbox-")
    const agent = path.join(orig, "agents", "test.md")
    const config = path.join(orig, "opencode.json")
    let stderr = ""

    await mkdir(path.dirname(agent), { recursive: true })
    await writeFile(config, JSON.stringify({ plugin }))
    await writeFile(agent, "test agent\n")

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
        "agents/test.md",
        "--prompt",
        "hello",
      ],
      { stdout: { write() {} }, stderr: { write(text) { stderr += text } } },
    )

    expect(status).toBe(1)
    expect(stderr).toContain(`Could not parse config file ${config}`)
    expect(stderr).not.toContain("Error:")
    expect(stderr).not.toContain("at ")
    expect(stderr).not.toContain("cli-v2.ts")
  })

  it("rejects absolute local plugin paths before copying sandbox files", async () => {
    const orig = await tempDir()
    const dest = await tempDir("cli-v2-sandbox-")
    const config = path.join(orig, "opencode.json")
    const plugin = path.join(orig, "plugins", "absolute.js")
    const agent = path.join(orig, "agents", "hello-world.md")

    await mkdir(path.dirname(plugin), { recursive: true })
    await mkdir(path.dirname(agent), { recursive: true })
    await writeFile(config, JSON.stringify({ plugin }, null, 2))
    await writeFile(plugin, "export const absolute = true\n")
    await writeFile(agent, "absolute plugin test agent\n")

    await expect(
      prepareSingleAgentSandbox({
        sourceRoot: orig,
        sandboxRoot: dest,
        agentName: "custom-agent",
        prompt: "Use the custom agent.",
        sourceConfigFile: config,
        sourceAgentFile: agent,
      }),
    ).rejects.toThrow(`Absolute local plugin paths are not supported in sandbox config: ${plugin}`)

    const sandboxRoot = path.resolve(dest)
    await expect(readFile(path.join(sandboxRoot, "config", "opencode", "opencode.json"), "utf8")).rejects.toThrow()
    await expect(readFile(path.join(sandboxRoot, "config", "opencode", "plugins", "absolute.js"), "utf8")).rejects.toThrow()
    await expect(readFile(path.join(sandboxRoot, "config", "opencode", "agents", "custom-agent.md"), "utf8")).rejects.toThrow()
  })

  it("rejects traversal plugin entries before copying any plugin files", async () => {
    const parent = await tempDir("cli-v2-source-parent-")
    const orig = path.join(parent, "source")
    const dest = await tempDir("cli-v2-sandbox-")
    const config = path.join(orig, "opencode.json")
    const safePlugin = path.join(orig, "plugins", "local.js")
    const evilPlugin = path.join(parent, "evil.js")
    const agent = path.join(orig, "agents", "hello-world.md")

    await mkdir(path.dirname(safePlugin), { recursive: true })
    await mkdir(path.dirname(agent), { recursive: true })
    await writeFile(config, JSON.stringify({ plugin: ["./plugins/local.js", "../evil.js"] }, null, 2))
    await writeFile(safePlugin, "export const local = true\n")
    await writeFile(evilPlugin, "export const evil = true\n")
    await writeFile(agent, "traversal plugin test agent\n")

    await expect(
      prepareSingleAgentSandbox({
        sourceRoot: orig,
        sandboxRoot: dest,
        agentName: "custom-agent",
        prompt: "Use the custom agent.",
        sourceConfigFile: config,
        sourceAgentFile: agent,
      }),
    ).rejects.toThrow("Configured local plugin escapes sandbox plugin directory: ../evil.js ->")

    const sandboxRoot = path.resolve(dest)
    await expect(readFile(path.join(sandboxRoot, "config", "evil.js"), "utf8")).rejects.toThrow()
    await expect(readFile(path.join(sandboxRoot, "config", "opencode", "plugins", "local.js"), "utf8")).rejects.toThrow()
  })

  it("rejects normalized plugin entries that escape the plugin directory", async () => {
    const orig = await tempDir()
    const dest = await tempDir("cli-v2-sandbox-")
    const config = path.join(orig, "opencode.json")
    const evilPlugin = path.join(orig, "evil.js")
    const agent = path.join(orig, "agents", "hello-world.md")

    await mkdir(path.dirname(agent), { recursive: true })
    await writeFile(config, JSON.stringify({ plugin: ["./plugins/../evil.js"] }, null, 2))
    await writeFile(evilPlugin, "export const evil = true\n")
    await writeFile(agent, "normalized traversal plugin test agent\n")

    await expect(
      prepareSingleAgentSandbox({
        sourceRoot: orig,
        sandboxRoot: dest,
        agentName: "custom-agent",
        prompt: "Use the custom agent.",
        sourceConfigFile: config,
        sourceAgentFile: agent,
      }),
    ).rejects.toThrow("Configured local plugin escapes sandbox plugin directory: ./plugins/../evil.js ->")

    await expect(readFile(path.join(path.resolve(dest), "config", "opencode", "evil.js"), "utf8")).rejects.toThrow()
  })

  it("rejects deep traversal plugin entries before writing outside the sandbox root", async () => {
    const parent = await tempDir("cli-v2-sandbox-parent-")
    const sourceRoot = path.join(parent, "source")
    const sourceConfigDir = path.join(sourceRoot, "config", "opencode")
    const dest = path.join(parent, "sandbox")
    const config = path.join(sourceConfigDir, "opencode.json")
    const escapePlugin = path.join(sourceRoot, "escape.js")
    const agent = path.join(sourceRoot, "agents", "hello-world.md")

    await mkdir(sourceConfigDir, { recursive: true })
    await mkdir(path.dirname(agent), { recursive: true })
    await writeFile(config, JSON.stringify({ plugin: ["../../escape.js"] }, null, 2))
    await writeFile(escapePlugin, "export const escape = true\n")
    await writeFile(agent, "deep traversal plugin test agent\n")

    await expect(
      prepareSingleAgentSandbox({
        sourceRoot,
        sandboxRoot: dest,
        agentName: "custom-agent",
        prompt: "Use the custom agent.",
        sourceConfigFile: config,
        sourceAgentFile: agent,
      }),
    ).rejects.toThrow("Configured local plugin escapes sandbox plugin directory: ../../escape.js ->")

    await expect(readFile(path.join(dest, "escape.js"), "utf8")).rejects.toThrow()
    await expect(readFile(path.join(parent, "escape.js"), "utf8")).rejects.toThrow()
  })

  it("invokes hello-world with isolated XDG env and the fixture agent", async () => {
    const dest = await tempDir("cli-v2-sandbox-")
    const bin = await tempDir("cli-v2-bin-")
    const recordPath = path.join(dest, "opencode-record.json")
    const fixtureAgent = path.join(process.cwd(), "sandbox", "fixtures", "agents", "hello-world.md")
    const fakeOpencode = path.join(bin, "opencode")

    await writeFile(
      fakeOpencode,
      `#!/usr/bin/env node\nimport { existsSync, readFileSync, writeFileSync } from "node:fs"\nimport path from "node:path"\nconst args = process.argv.slice(2)\nconst configDir = path.join(process.env.XDG_CONFIG_HOME, "opencode")\nconst config = JSON.parse(readFileSync(path.join(configDir, "opencode.json"), "utf8"))\nfor (const entry of config.plugin ?? []) {\n  if (typeof entry === "string" && (entry.startsWith("./") || entry.startsWith("../"))) {\n    if (!existsSync(path.resolve(configDir, entry))) process.exit(43)\n  }\n}\nwriteFileSync(${JSON.stringify(recordPath)}, JSON.stringify({ args, env: process.env }, null, 2))\nif (!args.includes("Respond with hello world.")) process.exit(42)\nprocess.exit(0)\n`,
    )
    await chmod(fakeOpencode, 0o755)

    const status = await runCli(
      ["node", "cli-v2", "hello-world", "--dest", dest],
      { stdout: { write() {} }, stderr: { write() {} } },
      { env: { ...process.env, PATH: `${bin}${path.delimiter}${process.env.PATH ?? ""}` } },
    )

    const record = JSON.parse(await readFile(recordPath, "utf8"))
    expect(status).toBe(0)
    expect(record.args).toEqual([
      "run",
      "--dir",
      path.join(path.resolve(dest), "worktree"),
      "--agent",
      "hello-world",
      "Respond with hello world.",
    ])
    expect(record.env.XDG_CONFIG_HOME).toBe(path.join(path.resolve(dest), "config"))
    expect(record.env.XDG_DATA_HOME).toBe(path.join(path.resolve(dest), "data"))
    expect(record.env.XDG_CACHE_HOME).toBe(path.join(path.resolve(dest), "cache"))
    expect(record.env.XDG_STATE_HOME).toBe(path.join(path.resolve(dest), "state"))
    expect(await readFile(path.join(path.resolve(dest), "config", "opencode", "agents", "hello-world.md"), "utf8")).toBe(
      await readFile(fixtureAgent, "utf8"),
    )
  })

  it("handles hello-world sources without a plugins directory", async () => {
    const orig = await tempDir()
    const dest = await tempDir("cli-v2-sandbox-")
    const bin = await tempDir("cli-v2-bin-")
    const fixtureAgent = path.join(orig, "sandbox", "fixtures", "agents", "hello-world.md")
    const fakeOpencode = path.join(bin, "opencode")

    await mkdir(path.dirname(fixtureAgent), { recursive: true })
    await writeFile(path.join(orig, "opencode.json"), "{\n  \"plugin\": []\n}")
    await writeFile(fixtureAgent, "hello-world fixture\n")
    await writeFile(fakeOpencode, "#!/usr/bin/env node\nprocess.exit(0)\n")
    await chmod(fakeOpencode, 0o755)

    const status = await runCli(
      ["node", "cli-v2", "hello-world", "--orig", orig, "--dest", dest],
      { stdout: { write() {} }, stderr: { write() {} } },
      { env: { ...process.env, PATH: `${bin}${path.delimiter}${process.env.PATH ?? ""}` } },
    )

    expect(status).toBe(0)
    expect(await readdir(path.join(path.resolve(dest), "config", "opencode", "plugins"))).toEqual([])
  })

  it("runs a generic single-agent sandbox with explicit files and prompt", async () => {
    const orig = await tempDir()
    const dest = await tempDir("cli-v2-sandbox-")
    const bin = await tempDir("cli-v2-bin-")
    const files = await writeSourceFiles(orig)
    const prompt = "Use the custom agent."
    const recordPath = path.join(dest, "opencode-record.json")
    const fakeOpencode = path.join(bin, "opencode")

    await writeFile(
      fakeOpencode,
      `#!/usr/bin/env node\nimport { existsSync, readFileSync, writeFileSync } from "node:fs"\nimport path from "node:path"\nconst args = process.argv.slice(2)\nconst configDir = path.join(process.env.XDG_CONFIG_HOME, "opencode")\nconst config = JSON.parse(readFileSync(path.join(configDir, "opencode.json"), "utf8"))\nfor (const entry of config.plugin ?? []) {\n  if (typeof entry === "string" && (entry.startsWith("./") || entry.startsWith("../"))) {\n    if (!existsSync(path.resolve(configDir, entry))) process.exit(43)\n  }\n}\nwriteFileSync(${JSON.stringify(recordPath)}, JSON.stringify({ args, env: process.env }, null, 2))\nprocess.exit(0)\n`,
    )
    await chmod(fakeOpencode, 0o755)

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
        "--prompt",
        prompt,
      ],
      { stdout: { write() {} }, stderr: { write() {} } },
      { env: { ...process.env, PATH: `${bin}${path.delimiter}${process.env.PATH ?? ""}` } },
    )

    const record = JSON.parse(await readFile(recordPath, "utf8"))
    const sandboxRoot = path.resolve(dest)
    const sandboxConfigFile = path.join(sandboxRoot, "config", "opencode", "opencode.json")
    const sandboxPluginDir = path.join(sandboxRoot, "config", "opencode", "plugins")
    const sandboxAgentFile = path.join(sandboxRoot, "config", "opencode", "agents", "custom-agent.md")

    expect(status).toBe(0)
    expect(record.args).toEqual([
      "run",
      "--dir",
      path.join(sandboxRoot, "worktree"),
      "--agent",
      "custom-agent",
      prompt,
    ])
    expect(record.env.XDG_CONFIG_HOME).toBe(path.join(sandboxRoot, "config"))
    expect(record.env.XDG_DATA_HOME).toBe(path.join(sandboxRoot, "data"))
    expect(record.env.XDG_CACHE_HOME).toBe(path.join(sandboxRoot, "cache"))
    expect(record.env.XDG_STATE_HOME).toBe(path.join(sandboxRoot, "state"))
    expect(await readFile(sandboxConfigFile, "utf8")).toBe(files.configText)
    expect((await readdir(sandboxPluginDir)).sort()).toEqual(["orchestration-state.js"])
    expect(await readFile(path.join(sandboxPluginDir, "orchestration-state.js"), "utf8")).toBe("export const pluginA = true\n")
    await expect(readFile(path.join(sandboxPluginDir, "stop-marker.js"), "utf8")).rejects.toThrow()
    expect(await readFile(sandboxAgentFile, "utf8")).toBe(
      await readFile(files.sourceAgentFile, "utf8"),
    )
    await expect(readFile(path.join(sandboxRoot, "config", "opencode", "agents", "hello-world.md"), "utf8")).rejects.toThrow()
  })

  it("runs single-agent with prompt text loaded from a file", async () => {
    const orig = await tempDir()
    const dest = await tempDir("cli-v2-sandbox-")
    const bin = await tempDir("cli-v2-bin-")
    const files = await writeSourceFiles(orig)
    const promptFile = path.join(orig, "prompt.md")
    const prompt = "Line one\nLine two"
    const recordPath = path.join(dest, "opencode-record.json")
    const fakeOpencode = path.join(bin, "opencode")

    await writeFile(promptFile, prompt)
    await writeFile(
      fakeOpencode,
      `#!/usr/bin/env node\nimport { writeFileSync } from "node:fs"\nwriteFileSync(${JSON.stringify(recordPath)}, JSON.stringify({ args: process.argv.slice(2) }, null, 2))\nprocess.exit(0)\n`,
    )
    await chmod(fakeOpencode, 0o755)

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
        "--prompt-file",
        "prompt.md",
      ],
      { stdout: { write() {} }, stderr: { write() {} } },
      { env: { ...process.env, PATH: `${bin}${path.delimiter}${process.env.PATH ?? ""}` } },
    )

    const record = JSON.parse(await readFile(recordPath, "utf8"))
    expect(status).toBe(0)
    expect(record.args.at(-1)).toBe(prompt)
  })

  it("rejects using both inline prompt and prompt file", async () => {
    let stderr = ""

    const status = await runCli(
      [
        "node",
        "cli-v2",
        "single-agent",
        "--agent",
        "custom-agent",
        "--agent-file",
        "agents/test.md",
        "--prompt",
        "hello",
        "--prompt-file",
        "prompt.md",
      ],
      { stdout: { write() {} }, stderr: { write(text) { stderr += text } } },
    )

    expect(status).toBe(1)
    expect(stderr).toBe("Use only one of --prompt or --prompt-file\n")
  })

  it("prepares scenario agents, fixtures, and candidate replacements", async () => {
    const orig = await tempDir()
    const scenarioRoot = await tempDir("cli-v2-scenario-")
    const dest = await tempDir("cli-v2-sandbox-")
    const config = path.join(orig, "opencode.json")
    const orchestrator = path.join(orig, "agents", "orchestrator.md")
    const planner = path.join(orig, "agents", "planner.md")
    const candidate = path.join(scenarioRoot, "candidate-orchestrator.md")

    await mkdir(path.dirname(orchestrator), { recursive: true })
    await mkdir(path.join(scenarioRoot, "worktree"), { recursive: true })
    await writeFile(config, JSON.stringify({ plugin: [] }, null, 2))
    await writeFile(orchestrator, "repo orchestrator\n")
    await writeFile(planner, "repo planner\n")
    await writeFile(candidate, "candidate orchestrator\n")
    await writeFile(path.join(scenarioRoot, "request.md"), "Do work.\n")
    await writeFile(path.join(scenarioRoot, "expected.json"), JSON.stringify({ assertions: [] }, null, 2))
    await writeFile(path.join(scenarioRoot, "worktree", "fixture.txt"), "fixture\n")
    await writeFile(
      path.join(scenarioRoot, "scenario.json"),
      JSON.stringify(
        {
          name: "candidate-test",
          primaryAgent: "orchestrator",
          agents: { orchestrator: "agents/orchestrator.md", planner: "agents/planner.md" },
          promptFile: "request.md",
          fixtureDir: "worktree",
          expectedFile: "expected.json",
        },
        null,
        2,
      ),
    )

    const status = await runCli(
      [
        "node",
        "cli-v2",
        "scenario",
        "--orig",
        orig,
        "--dest",
        dest,
        "--scenario",
        path.join(scenarioRoot, "scenario.json"),
        "--prepare-only",
        "--agent-candidate",
        `orchestrator=${candidate}`,
      ],
      { stdout: { write() {} }, stderr: { write() {} } },
    )

    const sandboxRoot = path.resolve(dest)
    expect(status).toBe(0)
    expect(await readFile(path.join(sandboxRoot, "config", "opencode", "agents", "orchestrator.md"), "utf8")).toBe("candidate orchestrator\n")
    expect(await readFile(path.join(sandboxRoot, "config", "opencode", "agents", "planner.md"), "utf8")).toBe("repo planner\n")
    expect(await readFile(path.join(sandboxRoot, "worktree", "fixture.txt"), "utf8")).toBe("fixture\n")
    expect(await readFile(orchestrator, "utf8")).toBe("repo orchestrator\n")
  })

  it("evaluates a captured scenario transcript and writes artifacts", async () => {
    const orig = await tempDir()
    const scenarioRoot = await tempDir("cli-v2-scenario-")
    const dest = await tempDir("cli-v2-sandbox-")
    const bin = await tempDir("cli-v2-bin-")
    const fakeOpencode = path.join(bin, "opencode")
    let stdout = ""
    let stderr = ""

    await mkdir(path.join(orig, "agents"), { recursive: true })
    await mkdir(path.join(scenarioRoot, "worktree"), { recursive: true })
    await writeFile(path.join(orig, "opencode.json"), JSON.stringify({ plugin: [] }, null, 2))
    await writeFile(path.join(orig, "agents", "orchestrator.md"), "orchestrator\n")
    await writeFile(path.join(scenarioRoot, "request.md"), "Review the code.\n")
    await writeFile(
      path.join(scenarioRoot, "expected.json"),
      JSON.stringify({ assertions: [{ name: "final", type: "finalResponseIncludes", required: ["done from transcript"] }] }, null, 2),
    )
    await writeFile(
      path.join(scenarioRoot, "scenario.json"),
      JSON.stringify(
        {
          name: "captured-test",
          primaryAgent: "orchestrator",
          agents: { orchestrator: "agents/orchestrator.md" },
          promptFile: "request.md",
          fixtureDir: "worktree",
          expectedFile: "expected.json",
        },
        null,
        2,
      ),
    )
    await writeFile(
      fakeOpencode,
      `#!/usr/bin/env node\nimport { writeFileSync } from "node:fs"\nconst events = [\n  { type: "task", agent: "planner", prompt: "make a plan", output: "plan" },\n  { type: "task", agent: "reviewer", prompt: "review", output: "verdict: APPROVED" },\n  { type: "tool", tool: "read", phase: "final-check" },\n  { type: "final_response", content: "done from transcript" }\n]\nwriteFileSync(process.env.OPENCODE_SANDBOX_TRACE_FILE, events.map((event) => JSON.stringify(event)).join("\\n") + "\\n")\nconsole.log("done from stdout")\nconsole.error("stderr text")\nprocess.exit(7)\n`,
    )
    await chmod(fakeOpencode, 0o755)

    const status = await runCli(
      [
        "node",
        "cli-v2",
        "evaluate",
        "--orig",
        orig,
        "--dest",
        dest,
        "--scenario",
        path.join(scenarioRoot, "scenario.json"),
        "--json",
      ],
      { stdout: { write(text) { stdout += text } }, stderr: { write(text) { stderr += text } } },
      { env: { ...process.env, PATH: `${bin}${path.delimiter}${process.env.PATH ?? ""}` } },
    )

    expect(stderr).toBe("")
    expect(status).toBe(0)
    const evaluation = JSON.parse(stdout)
    const outputDir = path.join(path.resolve(dest), "output")
    expect(evaluation.status).toBe(7)
    expect(evaluation.assertions).toEqual([{ name: "final", passed: true }])
    expect(evaluation.score_inputs.planner_prompts).toEqual(["make a plan"])
    expect(evaluation.score_inputs.readonly_tools_after_approval).toEqual([{ tool: "read", phase: "final-check" }])
    expect(await readFile(path.join(outputDir, "stdout.txt"), "utf8")).toBe("done from stdout\n")
    expect(await readFile(path.join(outputDir, "stderr.txt"), "utf8")).toBe("stderr text\n")
    expect(JSON.parse(await readFile(path.join(outputDir, "status.json"), "utf8"))).toEqual({ status: 7, timed_out: false, signal: null })
    expect(JSON.parse(await readFile(path.join(outputDir, "evaluation.json"), "utf8"))).toEqual(evaluation)
  })

  it("runs scripted scenarios through opencode so candidate content changes the score", async () => {
    const orig = await tempDir()
    const scenarioRoot = await tempDir("cli-v2-scenario-")
    const bin = await tempDir("cli-v2-bin-")
    const fakeOpencode = path.join(bin, "opencode")
    const goodDest = await tempDir("cli-v2-sandbox-")
    const badDest = await tempDir("cli-v2-sandbox-")
    const goodCandidate = path.join(scenarioRoot, "good-orchestrator.md")
    const badCandidate = path.join(scenarioRoot, "bad-orchestrator.md")

    await mkdir(path.join(orig, "agents"), { recursive: true })
    await mkdir(path.join(scenarioRoot, "worktree"), { recursive: true })
    await writeFile(path.join(orig, "opencode.json"), JSON.stringify({ plugin: [] }, null, 2))
    await writeFile(path.join(orig, "agents", "orchestrator.md"), "repo orchestrator\n")
    await writeFile(path.join(orig, "agents", "planner.md"), "planner\n")
    await writeFile(goodCandidate, "GOOD candidate prompt\n")
    await writeFile(badCandidate, "BAD candidate prompt\n")
    await writeFile(path.join(scenarioRoot, "request.md"), "Plan the request.\n")
    await writeFile(
      path.join(scenarioRoot, "expected.json"),
      JSON.stringify({ assertions: [{ name: "candidate_prompt", type: "taskPromptIncludes", agent: "planner", required: ["GOOD candidate prompt"] }] }, null, 2),
    )
    await writeFile(
      path.join(scenarioRoot, "scenario.json"),
      JSON.stringify(
        {
          name: "candidate-score",
          primaryAgent: "orchestrator",
          agents: { orchestrator: "agents/orchestrator.md", planner: "agents/planner.md" },
          promptFile: "request.md",
          fixtureDir: "worktree",
          expectedFile: "expected.json",
          scriptedSubagents: { planner: ["scripted planner output"] },
          transcript: [{ type: "task", agent: "planner", prompt: "synthetic stale prompt", output: "scripted planner output" }],
        },
        null,
        2,
      ),
    )
    await writeFile(
      fakeOpencode,
      `#!/usr/bin/env node
import { readFileSync, writeFileSync } from "node:fs"
import path from "node:path"
const args = process.argv.slice(2)
const agent = args[args.indexOf("--agent") + 1]
const agentFile = path.join(process.env.XDG_CONFIG_HOME, "opencode", "agents", agent + ".md")
const prompt = readFileSync(agentFile, "utf8").trim()
writeFileSync(process.env.OPENCODE_SANDBOX_TRACE_FILE, JSON.stringify({ type: "task", agent: "planner", prompt, output: "scripted planner output" }) + "\\n")
console.log("candidate run")
`,
    )
    await chmod(fakeOpencode, 0o755)

    async function evaluate(dest: string, candidate: string) {
      let stdout = ""
      const status = await runCli(
        ["node", "cli-v2", "evaluate", "--orig", orig, "--dest", dest, "--scenario", path.join(scenarioRoot, "scenario.json"), "--agent-candidate", `orchestrator=${candidate}`, "--json"],
        { stdout: { write(text) { stdout += text } }, stderr: { write() {} } },
        { env: { ...process.env, PATH: `${bin}${path.delimiter}${process.env.PATH ?? ""}` } },
      )
      expect(status).toBe(0)
      return JSON.parse(stdout)
    }

    const good = await evaluate(goodDest, goodCandidate)
    const bad = await evaluate(badDest, badCandidate)
    const generatedPlugin = await readFile(path.join(path.resolve(goodDest), "config", "opencode", "plugins", "sandbox-task-trace.js"), "utf8")

    expect(good.score_inputs.planner_prompts).toEqual(["GOOD candidate prompt"])
    expect(good.assertions[0]).toEqual({ name: "candidate_prompt", passed: true })
    expect(bad.score_inputs.planner_prompts).toEqual(["BAD candidate prompt"])
    expect(bad.assertions[0].passed).toBe(false)
    expect(generatedPlugin).toContain("export async function SandboxTracePlugin")
    expect(generatedPlugin).toContain("tool.execute.after")
    expect(generatedPlugin).toContain("scripted planner output")
  })

  it("records task, tool, and final-response events through the generated plugin", async () => {
    const orig = await tempDir()
    const scenarioRoot = await tempDir("cli-v2-scenario-")
    const dest = await tempDir("cli-v2-sandbox-")
    const bin = await tempDir("cli-v2-bin-")
    let stdout = ""

    await writeScenarioSource(orig, scenarioRoot, {
      scriptedSubagents: { planner: ["planner output"], reviewer: ["verdict: APPROVED"] },
      assertions: [
        { name: "final", type: "finalResponseIncludes", required: ["final from plugin"] },
        { name: "readonly", type: "readonlyToolOutputIncludes", required: ["pending"] },
      ],
    })
    await writePluginDrivingOpencode(bin, `
await hooks["tool.execute.after"]({ tool: "task", args: { subagent_type: "planner", prompt: "make a plan" } }, { output: "planner output" })
await hooks["tool.execute.after"]({ tool: "task", args: { subagent_type: "reviewer", prompt: "review" } }, { output: "verdict: APPROVED" })
await hooks["tool.execute.after"]({ tool: "read", args: { filePath: "status.txt" } }, { output: "pending", success: true })
await hooks["chat.message"]({}, { content: "final from plugin" })
`)

    const status = await runCli(
      ["node", "cli-v2", "evaluate", "--orig", orig, "--dest", dest, "--scenario", path.join(scenarioRoot, "scenario.json"), "--json"],
      { stdout: { write(text) { stdout += text } }, stderr: { write() {} } },
      { env: { ...process.env, PATH: `${bin}${path.delimiter}${process.env.PATH ?? ""}` } },
    )

    const evaluation = JSON.parse(stdout)
    const transcript = (await readFile(path.join(path.resolve(dest), "output", "transcript.jsonl"), "utf8"))
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line))
    const generatedPlugin = await readFile(path.join(path.resolve(dest), "config", "opencode", "plugins", "sandbox-task-trace.js"), "utf8")

    expect(status).toBe(0)
    expect(transcript.map((event) => event.type)).toEqual(["task", "task", "tool", "final_response"])
    expect(transcript[2]).toMatchObject({ type: "tool", tool: "read", phase: "after-approval", args: JSON.stringify({ filePath: "status.txt" }), output: "pending", result: "pending", success: true })
    expect(evaluation.trace_errors).toEqual([])
    expect(evaluation.score_inputs.final_response).toBe("final from plugin")
    expect(evaluation.score_inputs.readonly_tools_after_approval[0]).toMatchObject({ tool: "read", output: "pending" })
    expect(generatedPlugin).toContain("export async function SandboxTracePlugin")
    expect(generatedPlugin).not.toContain("replaceOutput")
  })

  it.each([
    {
      name: "unexpected",
      scriptedSubagents: { planner: ["planner output"] },
      calls: `await hooks["tool.execute.after"]({ tool: "task", args: { subagent_type: "reviewer", prompt: "review" } }, { output: "verdict: APPROVED" })`,
      message: "Unexpected task call for reviewer",
    },
    {
      name: "exhausted",
      scriptedSubagents: { planner: ["planner output"] },
      calls: `await hooks["tool.execute.after"]({ tool: "task", args: { subagent_type: "planner", prompt: "one" } }, { output: "planner output" })
await hooks["tool.execute.after"]({ tool: "task", args: { subagent_type: "planner", prompt: "two" } }, { output: "planner output" })`,
      message: "Exhausted scripted task outputs for planner at call 2",
    },
    {
      name: "mismatched",
      scriptedSubagents: { planner: ["expected planner output"] },
      calls: `await hooks["tool.execute.after"]({ tool: "task", args: { subagent_type: "planner", prompt: "plan" } }, { output: "different planner output" })`,
      message: "Scripted output mismatch for planner call 1",
    },
  ])("fails evaluation for $name scripted task expectations", async ({ scriptedSubagents, calls, message }) => {
    const orig = await tempDir()
    const scenarioRoot = await tempDir("cli-v2-scenario-")
    const dest = await tempDir("cli-v2-sandbox-")
    const bin = await tempDir("cli-v2-bin-")
    let stdout = ""

    await writeScenarioSource(orig, scenarioRoot, { scriptedSubagents })
    await writePluginDrivingOpencode(bin, `${calls}\nawait hooks["chat.message"]({}, { content: "done" })`)

    const status = await runCli(
      ["node", "cli-v2", "evaluate", "--orig", orig, "--dest", dest, "--scenario", path.join(scenarioRoot, "scenario.json"), "--json"],
      { stdout: { write(text) { stdout += text } }, stderr: { write() {} } },
      { env: { ...process.env, PATH: `${bin}${path.delimiter}${process.env.PATH ?? ""}` } },
    )

    const evaluation = JSON.parse(stdout)
    expect(status).toBe(0)
    expect(evaluation.trace_errors).toEqual([message])
    expect(evaluation.assertions).toContainEqual({ name: "trace_expectations", passed: false, message })
  })

  it("returns zero from non-JSON evaluate when all assertions pass", async () => {
    const orig = await tempDir()
    const scenarioRoot = await tempDir("cli-v2-scenario-")
    const dest = await tempDir("cli-v2-sandbox-")
    const bin = await tempDir("cli-v2-bin-")

    await writeScenarioSource(orig, scenarioRoot, { scriptedSubagents: { planner: ["planner output"] } })
    await writePluginDrivingOpencode(bin, `
await hooks["tool.execute.after"]({ tool: "task", args: { subagent_type: "planner", prompt: "plan" } }, { output: "planner output" })
await hooks["chat.message"]({}, { content: "done" })
`)

    const status = await runCli(
      ["node", "cli-v2", "evaluate", "--orig", orig, "--dest", dest, "--scenario", path.join(scenarioRoot, "scenario.json")],
      { stdout: { write() {} }, stderr: { write() {} } },
      { env: { ...process.env, PATH: `${bin}${path.delimiter}${process.env.PATH ?? ""}` } },
    )

    expect(status).toBe(0)
    await expect(readFile(path.join(path.resolve(dest), "output", "evaluation.json"), "utf8")).resolves.toContain("trace_errors")
  })

  it("returns one from non-JSON evaluate when an assertion fails", async () => {
    const orig = await tempDir()
    const scenarioRoot = await tempDir("cli-v2-scenario-")
    const dest = await tempDir("cli-v2-sandbox-")
    const bin = await tempDir("cli-v2-bin-")

    await writeScenarioSource(orig, scenarioRoot, {
      scriptedSubagents: { planner: ["planner output"] },
      assertions: [{ name: "final", type: "finalResponseIncludes", required: ["missing"] }],
    })
    await writePluginDrivingOpencode(bin, `
await hooks["tool.execute.after"]({ tool: "task", args: { subagent_type: "planner", prompt: "plan" } }, { output: "planner output" })
await hooks["chat.message"]({}, { content: "done" })
`)

    const status = await runCli(
      ["node", "cli-v2", "evaluate", "--orig", orig, "--dest", dest, "--scenario", path.join(scenarioRoot, "scenario.json")],
      { stdout: { write() {} }, stderr: { write() {} } },
      { env: { ...process.env, PATH: `${bin}${path.delimiter}${process.env.PATH ?? ""}` } },
    )

    expect(status).toBe(1)
  })

  it("fails clearly when a required trace is malformed", async () => {
    const orig = await tempDir()
    const scenarioRoot = await tempDir("cli-v2-scenario-")
    const dest = await tempDir("cli-v2-sandbox-")
    const bin = await tempDir("cli-v2-bin-")
    const fakeOpencode = path.join(bin, "opencode")
    let stderr = ""

    await mkdir(path.join(orig, "agents"), { recursive: true })
    await mkdir(path.join(scenarioRoot, "worktree"), { recursive: true })
    await writeFile(path.join(orig, "opencode.json"), JSON.stringify({ plugin: [] }, null, 2))
    await writeFile(path.join(orig, "agents", "orchestrator.md"), "orchestrator\n")
    await writeFile(path.join(scenarioRoot, "request.md"), "Do work.\n")
    await writeFile(path.join(scenarioRoot, "expected.json"), JSON.stringify({ assertions: [] }, null, 2))
    await writeFile(path.join(scenarioRoot, "scenario.json"), JSON.stringify({ name: "bad-trace", primaryAgent: "orchestrator", agents: { orchestrator: "agents/orchestrator.md" }, promptFile: "request.md", fixtureDir: "worktree", expectedFile: "expected.json" }, null, 2))
    await writeFile(fakeOpencode, `#!/usr/bin/env node
import { writeFileSync } from "node:fs"
writeFileSync(process.env.OPENCODE_SANDBOX_TRACE_FILE, "not json\\n")
`)
    await chmod(fakeOpencode, 0o755)

    const status = await runCli(
      ["node", "cli-v2", "evaluate", "--orig", orig, "--dest", dest, "--scenario", path.join(scenarioRoot, "scenario.json"), "--json"],
      { stdout: { write() {} }, stderr: { write(text) { stderr += text } } },
      { env: { ...process.env, PATH: `${bin}${path.delimiter}${process.env.PATH ?? ""}` } },
    )

    expect(status).toBe(1)
    expect(stderr).toContain("Malformed trace")
    expect(stderr).toContain("line 1")
  })

  it("fails clearly when a required trace is missing", async () => {
    const orig = await tempDir()
    const scenarioRoot = await tempDir("cli-v2-scenario-")
    const dest = await tempDir("cli-v2-sandbox-")
    const bin = await tempDir("cli-v2-bin-")
    const fakeOpencode = path.join(bin, "opencode")
    let stderr = ""

    await mkdir(path.join(orig, "agents"), { recursive: true })
    await mkdir(path.join(scenarioRoot, "worktree"), { recursive: true })
    await writeFile(path.join(orig, "opencode.json"), JSON.stringify({ plugin: [] }, null, 2))
    await writeFile(path.join(orig, "agents", "orchestrator.md"), "orchestrator\n")
    await writeFile(path.join(scenarioRoot, "request.md"), "Do work.\n")
    await writeFile(path.join(scenarioRoot, "expected.json"), JSON.stringify({ assertions: [] }, null, 2))
    await writeFile(path.join(scenarioRoot, "scenario.json"), JSON.stringify({ name: "missing-trace", primaryAgent: "orchestrator", agents: { orchestrator: "agents/orchestrator.md" }, promptFile: "request.md", fixtureDir: "worktree", expectedFile: "expected.json" }, null, 2))
    await writeFile(fakeOpencode, "#!/usr/bin/env node\nprocess.exit(0)\n")
    await chmod(fakeOpencode, 0o755)

    const status = await runCli(
      ["node", "cli-v2", "evaluate", "--orig", orig, "--dest", dest, "--scenario", path.join(scenarioRoot, "scenario.json")],
      { stdout: { write() {} }, stderr: { write(text) { stderr += text } } },
      { env: { ...process.env, PATH: `${bin}${path.delimiter}${process.env.PATH ?? ""}` } },
    )

    expect(status).toBe(1)
    expect(stderr).toContain("Required trace file was not written")
  })

  it("terminates timed out evaluations and writes structured artifacts", async () => {
    const orig = await tempDir()
    const scenarioRoot = await tempDir("cli-v2-scenario-")
    const dest = await tempDir("cli-v2-sandbox-")
    const bin = await tempDir("cli-v2-bin-")
    const fakeOpencode = path.join(bin, "opencode")
    let stdout = ""

    await mkdir(path.join(orig, "agents"), { recursive: true })
    await mkdir(path.join(scenarioRoot, "worktree"), { recursive: true })
    await writeFile(path.join(orig, "opencode.json"), JSON.stringify({ plugin: [] }, null, 2))
    await writeFile(path.join(orig, "agents", "orchestrator.md"), "orchestrator\n")
    await writeFile(path.join(scenarioRoot, "request.md"), "Do work.\n")
    await writeFile(path.join(scenarioRoot, "expected.json"), JSON.stringify({ assertions: [] }, null, 2))
    await writeFile(path.join(scenarioRoot, "scenario.json"), JSON.stringify({ name: "timeout", primaryAgent: "orchestrator", agents: { orchestrator: "agents/orchestrator.md" }, promptFile: "request.md", fixtureDir: "worktree", expectedFile: "expected.json" }, null, 2))
    await writeFile(fakeOpencode, "#!/usr/bin/env node\nsetTimeout(() => {}, 10000)\n")
    await chmod(fakeOpencode, 0o755)

    const status = await runCli(
      ["node", "cli-v2", "evaluate", "--orig", orig, "--dest", dest, "--scenario", path.join(scenarioRoot, "scenario.json"), "--timeout-ms", "25", "--json"],
      { stdout: { write(text) { stdout += text } }, stderr: { write() {} } },
      { env: { ...process.env, PATH: `${bin}${path.delimiter}${process.env.PATH ?? ""}` } },
    )

    const evaluation = JSON.parse(stdout)
    const outputDir = path.join(path.resolve(dest), "output")
    expect(status).toBe(0)
    expect(evaluation.status).toBe(124)
    expect(evaluation.timed_out).toBe(true)
    expect(JSON.parse(await readFile(path.join(outputDir, "status.json"), "utf8")).timed_out).toBe(true)
    expect(JSON.parse(await readFile(path.join(outputDir, "result.json"), "utf8")).timedOut).toBe(true)
    expect(JSON.parse(await readFile(path.join(outputDir, "evaluation.json"), "utf8"))).toEqual(evaluation)
  })

  it("returns a clean failure when opencode is missing", async () => {
    const orig = await tempDir()
    const dest = await tempDir("cli-v2-sandbox-")
    const files = await writeSourceFiles(orig)
    let stderr = ""

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
        "--prompt",
        "Hello from missing CLI test.",
      ],
      { stdout: { write() {} }, stderr: { write(text) { stderr += text } } },
      { env: { PATH: "" } },
    )

    expect(status).toBe(127)
    expect(stderr).toContain("opencode CLI was not found")
  })

  it("returns a clean validation error for missing single-agent options", async () => {
    let stderr = ""

    const status = await runCli(
      ["node", "cli-v2", "single-agent"],
      { stdout: { write() {} }, stderr: { write(text) { stderr += text } } },
    )

    expect(status).toBe(1)
    expect(stderr).toBe("--agent is required\n")
    expect(stderr).not.toContain("Error:")
    expect(stderr).not.toContain("at ")
    expect(stderr).not.toContain("cli-v2.ts")
  })

  it("returns a clean usage error for unknown single-agent options", async () => {
    let stderr = ""

    const status = await runCli(
      ["node", "cli-v2", "single-agent", "--unknown"],
      { stdout: { write() {} }, stderr: { write(text) { stderr += text } } },
    )

    expect(status).toBe(1)
    expect(stderr).toBe("Unknown option `--unknown`\n")
    expect(stderr).not.toContain("Error:")
    expect(stderr).not.toContain("at ")
    expect(stderr).not.toContain("cli-v2.ts")
  })

  it("does not advertise or run unsupported commands", async () => {
    let stdout = ""
    let stderr = ""

    const helpStatus = await runCli(["node", "cli-v2", "--help"], {
      stdout: { write(text) { stdout += text } },
      stderr: { write(text) { stderr += text } },
    })
    const unknownStatus = await runCli(["node", "cli-v2", "removed-command"], {
      stdout: { write(text) { stdout += text } },
      stderr: { write(text) { stderr += text } },
    })

    expect(helpStatus).toBe(0)
    expect(stdout).not.toContain("removed-command")
    expect(unknownStatus).toBe(1)
    expect(stderr).toContain("Unknown command: removed-command")
  })

  it("returns success for supported global help and hello --help", async () => {
    let stdout = ""
    let stderr = ""

    const globalHelpStatus = await runCli(["node", "cli-v2", "--help"], {
      stdout: { write(text) { stdout += text } },
      stderr: { write(text) { stderr += text } },
    })
    const helloHelpStatus = await runCli(["node", "cli-v2", "hello", "--help"], {
      stdout: { write(text) { stdout += text } },
      stderr: { write(text) { stderr += text } },
    })

    expect(globalHelpStatus).toBe(0)
    expect(helloHelpStatus).toBe(0)
    expect(stderr).toBe("")
  })

  it("newline-terminates the No command provided error", async () => {
    let stderr = ""

    const status = await runCli(["node", "cli-v2"], {
      stdout: { write() {} },
      stderr: { write(text) { stderr += text } },
    })

    expect(status).toBe(1)
    expect(stderr).toBe("No command provided.\n")
  })

  it("restores console.info after CLI runs", async () => {
    const originalConsoleInfo = console.info

    await runCli(["node", "cli-v2", "hello"], {
      stdout: { write() {} },
      stderr: { write() {} },
    })
    expect(console.info).toBe(originalConsoleInfo)

    await runCli(["node", "cli-v2", "removed-command"], {
      stdout: { write() {} },
      stderr: { write() {} },
    })
    expect(console.info).toBe(originalConsoleInfo)
  })

  it("runs the hello command through cac", async () => {
    let stdout = ""
    let stderr = ""

    const status = await runCli(["node", "cli-v2", "hello"], {
      stdout: {
        write(text) {
          stdout += text
        },
      },
      stderr: {
        write(text) {
          stderr += text
        },
      },
    })

    expect(status).toBe(0)
    expect(stdout).toBe("hello world\n")
    expect(stderr).toBe("")
  })
})
