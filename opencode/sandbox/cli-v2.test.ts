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
