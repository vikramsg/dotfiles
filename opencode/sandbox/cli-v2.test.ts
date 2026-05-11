import { chmod, mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises"
import os from "node:os"
import path from "node:path"
import { describe, expect, it } from "vitest"
import {
  copyAgentFileToSandbox,
  copyConfigFileToSandbox,
  copyPluginFileToSandbox,
  createSingleAgentSandboxLayout,
  runCli,
} from "./cli-v2.js"

async function tempDir(name = "cli-v2-test-") {
  return mkdtemp(path.join(os.tmpdir(), name))
}

async function writeSourceFiles(root: string) {
  const config = path.join(root, "opencode.json")
  const plugin = path.join(root, "plugins", "orchestration-state.js")
  const agent = path.join(root, "agents", "hello-world.md")

  await mkdir(path.dirname(plugin), { recursive: true })
  await mkdir(path.dirname(agent), { recursive: true })

  await writeFile(
    config,
    JSON.stringify(
      {
        plugin: ["opencode-websearch-cited@1.2.0", "./plugins/orchestration-state.js"],
      },
      null,
      2,
    ),
  )
  await writeFile(plugin, "export const plugin = true\n")
  await writeFile(agent, "---\ndescription: hello world\n---\n\nSay hello world.\n")

  return {
    sourceConfigFile: config,
    sourcePluginFile: plugin,
    sourceAgentFile: agent,
  }
}

describe("cli-v2", () => {
  it("prints strict-plan command help without running the sandbox", async () => {
    let stdout = ""
    let stderr = ""

    const status = await runCli(["node", "cli-v2", "strict-plan", "--help"], {
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
    expect(stdout).toContain("Run the strict-plan agent")
    expect(stdout).toContain("--prompt <text>")
    expect(stderr).toBe("")
  })

  it("documents strict-plan native OpenCode plan source provenance", async () => {
    const prompt = await readFile(
      path.join(process.cwd(), "sandbox", "fixtures", "agents", "strict-plan.md"),
      "utf8",
    )

    expect(prompt).toContain("native agent `plan`")
    expect(prompt).toContain("packages/opencode/src/agent/agent.ts")
    expect(prompt).toContain("packages/opencode/src/session/prompt/plan.txt")
    expect(prompt).toContain("OpenCode 1.14.41")
    expect(prompt).not.toContain("opencode/agents/planner.md")
  })

  it("documents strict-plan native read-only behavior", async () => {
    const prompt = await readFile(
      path.join(process.cwd(), "sandbox", "fixtures", "agents", "strict-plan.md"),
      "utf8",
    )

    expect(prompt).toContain("Plan mode is read-only")
    expect(prompt).toContain("reading, searching, thinking")
    expect(prompt).toContain("delegated exploration")
    expect(prompt).toContain("Do not edit, write, implement")
    expect(prompt).toContain("mutate files")
    expect(prompt).toContain("non-read-only tools")
    expect(prompt).toContain("change system state")
    expect(prompt).toContain("Ask clarifying questions")
    expect(prompt).toContain("requirements are blocked")
    expect(prompt).toContain("well-formed, concise, executable plan")
  })

  it("documents strict-plan final output and language contracts", async () => {
    const prompt = await readFile(
      path.join(process.cwd(), "sandbox", "fixtures", "agents", "strict-plan.md"),
      "utf8",
    )

    for (const section of [
      "`Executive Summary`",
      "`Assumptions`",
      "`Architecture and Data Flow`",
      "`Impact Matrix`",
      "`Acceptance Scenarios`",
      "`Patterns`",
      "`Implementation Checklist`",
      "`Verification Commands`",
      "`Review Focus`",
    ]) {
      expect(prompt).toContain(section)
    }

    expect(prompt).toContain("Assumptions is mandatory")
    expect(prompt).toContain("Patterns is mandatory")
    expect(prompt).toContain("docstring")
    expect(prompt).toContain("where comments or docstrings should be added")
    expect(prompt).toContain("where comments or docstrings should not be added")
    expect(prompt).toContain("why")
    expect(prompt).toContain("Do not use vague `if`, `maybe`, or `but` language")
    expect(prompt).toContain("If X is found, do A; otherwise do B")
  })

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

  it("copies config and rewrites only the local plugin to the sandbox plugin", async () => {
    const orig = await tempDir()
    const dest = await tempDir("cli-v2-sandbox-")
    const files = await writeSourceFiles(orig)
    const layout = await createSingleAgentSandboxLayout({ sandboxRoot: dest })
    const sandboxPluginFile = path.join(layout.pluginDir, path.basename(files.sourcePluginFile))

    await copyPluginFileToSandbox({
      sourcePluginFile: files.sourcePluginFile,
      sandboxPluginFile,
    })
    await copyConfigFileToSandbox({
      sourceConfigFile: files.sourceConfigFile,
      sandboxConfigFile: layout.sandboxConfigFile,
      sourcePluginFile: files.sourcePluginFile,
      sandboxPluginFile,
    })

    const copiedPlugin = await readFile(sandboxPluginFile, "utf8")
    const copiedConfig = JSON.parse(await readFile(layout.sandboxConfigFile, "utf8"))

    expect(copiedPlugin).toBe("export const plugin = true\n")
    expect(copiedConfig.plugin).toEqual([
      "opencode-websearch-cited@1.2.0",
      sandboxPluginFile,
    ])
  })

  it("copies an explicit agent file into the sandbox", async () => {
    const orig = await tempDir()
    const dest = await tempDir("cli-v2-sandbox-")
    const files = await writeSourceFiles(orig)
    const layout = await createSingleAgentSandboxLayout({ sandboxRoot: dest })
    const sandboxAgentFile = path.join(layout.agentDir, path.basename(files.sourceAgentFile))

    await copyAgentFileToSandbox({
      sourceAgentFile: files.sourceAgentFile,
      sandboxAgentFile,
    })

    expect(await readFile(sandboxAgentFile, "utf8")).toBe(
      await readFile(files.sourceAgentFile, "utf8"),
    )
  })

  it("runs a generic single-agent sandbox with an explicit prompt", async () => {
    const orig = await tempDir()
    const dest = await tempDir("cli-v2-sandbox-")
    const bin = await tempDir("cli-v2-bin-")
    const files = await writeSourceFiles(orig)
    const prompt = "Use the custom agent."
    const recordPath = path.join(dest, "opencode-record.json")
    const fakeOpencode = path.join(bin, "opencode")

    const expectedConfigHome = path.join(path.resolve(dest), "config")
    const expectedAgentFile = path.join(expectedConfigHome, "opencode", "agents", "custom-agent.md")
    await writeFile(
      fakeOpencode,
      `#!/usr/bin/env node\nimport { existsSync, readFileSync, writeFileSync } from "node:fs"\nimport path from "node:path"\nconst args = process.argv.slice(2)\nwriteFileSync(${JSON.stringify(recordPath)}, JSON.stringify({ args, env: process.env }, null, 2))\nconst expectedConfigHome = ${JSON.stringify(expectedConfigHome)}\nconst expectedAgentFile = ${JSON.stringify(expectedAgentFile)}\nif (process.env.XDG_CONFIG_HOME !== expectedConfigHome) { console.error("unexpected XDG_CONFIG_HOME"); process.exit(41) }\nif (args.at(-1) !== ${JSON.stringify(prompt)}) { console.error("unexpected prompt"); process.exit(42) }\nconst agentName = args[args.indexOf("--agent") + 1]\nif (agentName !== "custom-agent") { console.error("unexpected agent"); process.exit(43) }\nconst configFile = path.join(process.env.XDG_CONFIG_HOME, "opencode", "opencode.json")\nif (!existsSync(configFile)) { console.error("missing config"); process.exit(44) }\nconst config = JSON.parse(readFileSync(configFile, "utf8"))\nconst plugins = Array.isArray(config.plugin) ? config.plugin : [config.plugin]\nconst pluginFile = plugins.find((entry) => typeof entry === "string" && entry.endsWith("orchestration-state.js"))\nif (!pluginFile || !existsSync(pluginFile)) { console.error("missing rewritten plugin"); process.exit(45) }\nif (!existsSync(expectedAgentFile)) { console.error("missing requested agent file"); process.exit(46) }\nprocess.exit(0)\n`,
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
    expect(status).toBe(0)
    expect(record.args).toEqual([
      "run",
      "--dir",
      path.join(path.resolve(dest), "worktree"),
      "--agent",
      "custom-agent",
      prompt,
    ])
    expect(await readFile(path.join(path.resolve(dest), "config", "opencode", "agents", "custom-agent.md"), "utf8")).toBe(
      await readFile(files.sourceAgentFile, "utf8"),
    )
    await expect(readFile(path.join(path.resolve(dest), "config", "opencode", "agents", "hello-world.md"), "utf8")).rejects.toThrow()
  })

  it("invokes fake opencode with isolated XDG env", async () => {
    const dest = await tempDir("cli-v2-sandbox-")
    const bin = await tempDir("cli-v2-bin-")
    const recordPath = path.join(dest, "opencode-record.json")
    const fixtureAgent = path.join(process.cwd(), "sandbox", "fixtures", "agents", "hello-world.md")
    const fakeOpencode = path.join(bin, "opencode")

    await writeFile(
      fakeOpencode,
      `#!/usr/bin/env node\nimport { writeFileSync } from "node:fs"\nconst args = process.argv.slice(2)\nwriteFileSync(${JSON.stringify(recordPath)}, JSON.stringify({ args, env: process.env }, null, 2))\nif (!args.includes("Respond with hello world.")) process.exit(42)\nprocess.exit(0)\n`,
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

  it("runs the strict-plan sandbox command with isolated config and prompt", async () => {
    const dest = await tempDir("cli-v2-sandbox-")
    const bin = await tempDir("cli-v2-bin-")
    const prompt = "Plan a no-op documentation check. Do not edit files."
    const recordPath = path.join(dest, "opencode-record.json")
    const fakeOpencode = path.join(bin, "opencode")
    const expectedRoot = path.resolve(dest)
    const expectedConfigHome = path.join(expectedRoot, "config")
    const expectedAgentFile = path.join(expectedConfigHome, "opencode", "agents", "strict-plan.md")
    const fixtureAgent = path.join(process.cwd(), "sandbox", "fixtures", "agents", "strict-plan.md")

    await writeFile(
      fakeOpencode,
      `#!/usr/bin/env node
import { existsSync, readFileSync, writeFileSync } from "node:fs"
import path from "node:path"
const args = process.argv.slice(2)
writeFileSync(${JSON.stringify(recordPath)}, JSON.stringify({ args, env: process.env }, null, 2))
const expectedAgentFile = ${JSON.stringify(expectedAgentFile)}
if (process.env.XDG_CONFIG_HOME !== ${JSON.stringify(expectedConfigHome)}) process.exit(41)
if (process.env.XDG_DATA_HOME !== ${JSON.stringify(path.join(expectedRoot, "data"))}) process.exit(42)
if (process.env.XDG_CACHE_HOME !== ${JSON.stringify(path.join(expectedRoot, "cache"))}) process.exit(43)
if (process.env.XDG_STATE_HOME !== ${JSON.stringify(path.join(expectedRoot, "state"))}) process.exit(44)
if (args.join("\u0000") !== ${JSON.stringify(["run", "--dir", path.join(expectedRoot, "worktree"), "--agent", "strict-plan", prompt].join("\u0000"))}) process.exit(45)
if (!existsSync(expectedAgentFile)) process.exit(46)
const configFile = path.join(process.env.XDG_CONFIG_HOME, "opencode", "opencode.json")
if (!existsSync(configFile)) process.exit(47)
const config = JSON.parse(readFileSync(configFile, "utf8"))
const plugins = Array.isArray(config.plugin) ? config.plugin : [config.plugin]
const pluginFile = plugins.find((entry) => typeof entry === "string" && entry.endsWith("orchestration-state.js"))
if (!pluginFile || !existsSync(pluginFile)) process.exit(48)
process.exit(0)
`,
    )
    await chmod(fakeOpencode, 0o755)

    const status = await runCli(
      ["node", "cli-v2", "strict-plan", "--dest", dest, "--prompt", prompt],
      { stdout: { write() {} }, stderr: { write() {} } },
      { env: { ...process.env, PATH: `${bin}${path.delimiter}${process.env.PATH ?? ""}` } },
    )

    const record = JSON.parse(await readFile(recordPath, "utf8"))
    expect(status).toBe(0)
    expect(record.args).toEqual([
      "run",
      "--dir",
      path.join(expectedRoot, "worktree"),
      "--agent",
      "strict-plan",
      prompt,
    ])
    expect(record.env.XDG_CONFIG_HOME).toBe(expectedConfigHome)
    expect(record.env.XDG_DATA_HOME).toBe(path.join(expectedRoot, "data"))
    expect(record.env.XDG_CACHE_HOME).toBe(path.join(expectedRoot, "cache"))
    expect(record.env.XDG_STATE_HOME).toBe(path.join(expectedRoot, "state"))
    expect(await readFile(expectedAgentFile, "utf8")).toBe(await readFile(fixtureAgent, "utf8"))
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
