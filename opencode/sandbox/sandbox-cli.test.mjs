import test from "node:test"
import assert from "node:assert/strict"
import { spawn } from "node:child_process"
import { mkdtemp, mkdir, writeFile, readFile } from "node:fs/promises"
import { existsSync } from "node:fs"
import os from "node:os"
import path from "node:path"

const repoOpencode = path.resolve(import.meta.dirname, "..")
const cli = path.join(repoOpencode, "sandbox", "dist", "sandbox-cli.js")

async function makeFakeOpencode({ marker = true, log = "", events = "default", signal = null } = {}) {
  const root = await mkdtemp(path.join(os.tmpdir(), "fake-opencode-"))
  const bin = path.join(root, "bin")
  await mkdir(bin)
  const executable = path.join(bin, "opencode")
  await writeFile(executable, `#!/usr/bin/env node
import fs from "node:fs"
import path from "node:path"
import { pathToFileURL } from "node:url"
const args = process.argv.slice(2)
const agentIndex = args.indexOf("--agent")
const commandIndex = args.indexOf("--command")
const runAgent = agentIndex >= 0 ? args[agentIndex + 1] : null
const isOrchestrator = commandIndex >= 0 && args[commandIndex + 1] === "orchestrate"
const callID = "call-123"
const target = process.env.OPENCODE_SANDBOX_SINGLE_AGENT || process.env.OPENCODE_SANDBOX_STOP_AT || "planner"
async function loadGeneratedHooks() {
  const configHome = process.env.XDG_CONFIG_HOME
  if (!configHome) throw new Error("XDG_CONFIG_HOME is required")
  const configPath = path.join(configHome, "opencode", "opencode.json")
  const config = JSON.parse(fs.readFileSync(configPath, "utf8"))
  const generatedPluginDir = path.join(configHome, "opencode", "plugins")
  const plugins = Array.isArray(config.plugin) ? config.plugin : []
  const generatedPluginPaths = plugins.filter((plugin) => typeof plugin === "string" && path.isAbsolute(plugin) && plugin.startsWith(generatedPluginDir + path.sep))
  if (${marker} && generatedPluginPaths.length === 0) throw new Error("generated plugin path missing from sandbox config")
  const hooks = []
  for (const pluginPath of generatedPluginPaths) {
    const module = await import(pathToFileURL(pluginPath).href)
    for (const exported of Object.values(module)) {
      if (typeof exported !== "function") continue
      const pluginHooks = await exported()
      if (pluginHooks && typeof pluginHooks === "object") hooks.push(pluginHooks)
    }
  }
  return hooks
}
async function invokeGeneratedHook(name, input, output) {
  if (!${marker}) return
  for (const hooks of await loadGeneratedHooks()) {
    if (typeof hooks[name] === "function") await hooks[name](input, output)
  }
}
if (${JSON.stringify(log)} !== "") fs.writeSync(2, ${JSON.stringify(log)})
if (${JSON.stringify(events)} === "bad") {
  fs.writeSync(1, '{"type":"step_start"}\\n')
} else {
  fs.writeSync(1, JSON.stringify({ type: "step_start", args }) + "\\n")
  fs.writeSync(1, JSON.stringify({ type: "tool", callID, nested: { value: callID }, agent: runAgent, target }) + "\\n")
}
const taskInput = { tool: "task", args: { subagent_type: target }, callID }
const taskOutput = { title: null, output: null }
await invokeGeneratedHook("tool.execute.before", taskInput, taskOutput)
await invokeGeneratedHook("tool.execute.after", taskInput, taskOutput)
const signal = ${JSON.stringify(signal)}
if (signal) {
  await new Promise((resolve) => setTimeout(resolve, 10))
  process.kill(process.pid, signal)
  await new Promise(() => {})
}
`, { mode: 0o755 })
  return bin
}

async function readEvents(sandboxRoot) {
  const text = await readFile(path.join(sandboxRoot, "output", "events.jsonl"), "utf8")
  return text.trim().split("\n").map((line) => JSON.parse(line))
}

async function runCli(args, { env = {}, fakeOptions } = {}) {
  const sandboxRoot = await mkdtemp(path.join(os.tmpdir(), "sandbox-cli-test-"))
  const fakeBin = fakeOptions === false ? null : await makeFakeOpencode(fakeOptions)
  const childEnv = {
    ...process.env,
    ...env,
    OPENCODE_SANDBOX_ROOT: sandboxRoot,
    PATH: fakeBin ? `${fakeBin}${path.delimiter}${process.env.PATH || ""}` : "",
  }
  const result = await new Promise((resolve) => {
    const child = spawn(process.execPath, [cli, ...args], { env: childEnv })
    let stdout = ""
    let stderr = ""
    child.stdout.on("data", (chunk) => stdout += chunk)
    child.stderr.on("data", (chunk) => stderr += chunk)
    child.on("close", (status) => resolve({ status, stdout, stderr, sandboxRoot }))
  })
  return result
}

test("orchestrator-until planner succeeds with generated stop marker", async () => {
  const result = await runCli(["orchestrator-until", "planner", "make", "a", "plan"])
  assert.equal(result.status, 0, result.stderr)
  const marker = JSON.parse(await readFile(path.join(result.sandboxRoot, "output", "stop-marker.json"), "utf8"))
  assert.equal(marker.subagent, "planner")
  assert.equal(await readFile(path.join(result.sandboxRoot, "output", "exit-status.txt"), "utf8"), "0\n")
})

test("orchestrator-until preserves prompt tokens that start with dash", async () => {
  const result = await runCli(["orchestrator-until", "planner", "please", "--review", "this"])
  assert.equal(result.status, 0, result.stderr)
  const events = await readEvents(result.sandboxRoot)
  assert.ok(events.some((event) => event.args?.includes("please --review this")), JSON.stringify(events))
})

test("orchestrator-until invalid stop phase exits 64", async () => {
  const result = await runCli(["orchestrator-until", "planner", "prompt"], { env: { OPENCODE_SANDBOX_STOP_PHASE: "during" } })
  assert.equal(result.status, 64)
  assert.match(result.stderr, /OPENCODE_SANDBOX_STOP_PHASE/)
})

test("single-agent planner uses harness and validates marker", async () => {
  const result = await runCli(["single-agent", "planner", "prompt"])
  assert.equal(result.status, 0, result.stderr)
  const metadata = JSON.parse(await readFile(path.join(result.sandboxRoot, "output", "metadata.json"), "utf8"))
  const marker = JSON.parse(await readFile(path.join(result.sandboxRoot, "output", "single-agent-marker.json"), "utf8"))
  assert.equal(metadata.agentMode, "subagent")
  assert.equal(metadata.runAgent, "sandbox-single-agent-harness")
  assert.equal(marker.observedSubagent, "planner")
  assert.ok(existsSync(path.join(result.sandboxRoot, "config", "opencode", "agents", "sandbox-single-agent-harness.md")))
})

test("single-agent preserves prompt tokens that start with dash", async () => {
  const result = await runCli(["single-agent", "planner", "please", "--keep-this", "now"])
  assert.equal(result.status, 0, result.stderr)
  const events = await readEvents(result.sandboxRoot)
  assert.ok(events.some((event) => event.args?.some((arg) => arg.includes("please --keep-this now"))), JSON.stringify(events))
})

test("single-agent preserves signal exit status", async () => {
  const result = await runCli(["single-agent", "planner", "prompt"], { fakeOptions: { signal: "SIGTERM" } })
  assert.equal(result.status, 143, result.stderr)
  assert.equal(await readFile(path.join(result.sandboxRoot, "output", "opencode-exit-status.txt"), "utf8"), "143\n")
})

test("single-agent orchestrator runs primary agent directly", async () => {
  const result = await runCli(["single-agent", "orchestrator", "prompt"])
  assert.equal(result.status, 0, result.stderr)
  const metadata = JSON.parse(await readFile(path.join(result.sandboxRoot, "output", "metadata.json"), "utf8"))
  assert.equal(metadata.agentMode, "primary")
  assert.equal(metadata.runAgent, "orchestrator")
})

test("missing agent exits 66", async () => {
  const result = await runCli(["single-agent", "missing-agent", "prompt"])
  assert.equal(result.status, 66)
  assert.match(result.stderr, /agent file was not found/)
})

test("missing opencode exits 127", async () => {
  const result = await runCli(["single-agent", "planner", "prompt"], { fakeOptions: false })
  assert.equal(result.status, 127)
  assert.match(result.stderr, /opencode CLI was not found/)
})

test("real database path in log causes final status 1", async () => {
  const realDb = path.join(process.env.XDG_DATA_HOME || path.join(os.homedir(), ".local", "share"), "opencode", "opencode.db")
  const result = await runCli(["single-agent", "planner", "prompt"], { fakeOptions: { log: `using ${realDb}\n` } })
  assert.equal(result.status, 1)
  assert.match(result.stderr, /validation error: log contains user OpenCode database path/)
})
