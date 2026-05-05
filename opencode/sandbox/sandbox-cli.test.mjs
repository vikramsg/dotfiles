import test from "node:test"
import assert from "node:assert/strict"
import { spawn } from "node:child_process"
import { mkdtemp, mkdir, writeFile, readFile } from "node:fs/promises"
import { existsSync } from "node:fs"
import os from "node:os"
import path from "node:path"

const repoOpencode = path.resolve(import.meta.dirname, "..")
const cli = path.join(repoOpencode, "sandbox", "dist", "sandbox-cli.js")
const highEntropyTaskPrompt = Array.from({ length: 80 }, (_, index) => `VX-CAPTURE-${index.toString().padStart(2, "0")}-{A|B}->C`).join("\n")

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
if (${JSON.stringify(events)} === "final-check-approved" || ${JSON.stringify(events)} === "final-check-missing-read" || ${JSON.stringify(events)} === "final-check-missing-judgment") {
  const reviewerInput = { tool: "task", args: { subagent_type: "reviewer", prompt: "review this" }, callID: "review-call" }
  await invokeGeneratedHook("tool.execute.after", reviewerInput, { title: "reviewer", output: "verdict: APPROVED\\n", args: reviewerInput.args })
  fs.writeSync(1, JSON.stringify({ type: "tool", tool: "task", callID: "review-call", args: reviewerInput.args, output: "verdict: APPROVED" }) + "\\n")
  if (${JSON.stringify(events)} !== "final-check-missing-read") {
    const readInput = { tool: "read", args: { filePath: "/tmp/final-pr-check-demo.txt" }, callID: "read-call" }
    await invokeGeneratedHook("tool.execute.after", readInput, { title: "read", output: "one sentence" })
    fs.writeSync(1, JSON.stringify({ type: "tool", tool: "read", callID: "read-call", args: readInput.args }) + "\\n")
  }
  const finalText = ${JSON.stringify(events)} === "final-check-missing-judgment" ? "## Outcome\\n- done" : "## Orchestrator Merge-Readiness Judgment\\n- merge_ready: YES\\n- I inspected the changed files with read-only tools."
  fs.writeSync(1, JSON.stringify({ type: "message", role: "assistant", text: finalText }) + "\\n")
} else {
  const taskArgs = { subagent_type: target, prompt: ${JSON.stringify(highEntropyTaskPrompt)} }
  const taskInput = { tool: "task", args: taskArgs, callID }
  const beforeTaskInput = { tool: "task", args: { subagent_type: target + "-stale", prompt: "STALE-BEFORE-PROMPT" }, callID }
  const beforeTaskOutput = { args: taskArgs }
  const afterTaskOutput = { title: null, output: null, args: { subagent_type: target + "-stale", prompt: "STALE-AFTER-PROMPT" } }
  await invokeGeneratedHook("tool.execute.before", beforeTaskInput, beforeTaskOutput)
  await invokeGeneratedHook("tool.execute.after", taskInput, afterTaskOutput)
}
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
  const metadata = JSON.parse(await readFile(path.join(result.sandboxRoot, "output", "metadata.json"), "utf8"))
  const marker = JSON.parse(await readFile(path.join(result.sandboxRoot, "output", "stop-marker.json"), "utf8"))
  assert.equal(Object.hasOwn(metadata, "stateRoot"), false)
  assert.equal(marker.subagent, "planner")
  assert.equal(marker.inputArgs.prompt, highEntropyTaskPrompt)
  assert.ok(marker.inputArgs.prompt.length > 1200)
  assert.doesNotMatch(marker.inputArgs.prompt, /\.agents\/tasks/)
  assert.doesNotMatch(marker.inputArgs.prompt, /request\.md/)
  assert.doesNotMatch(marker.inputArgs.prompt, /NO_[A-Z_]*PLAN[A-Z_]*/)
  assert.doesNotMatch(marker.inputArgs.prompt, /BEGIN_VERBATIM_USER_PLAN/)
  assert.doesNotMatch(result.stdout, /Persistent state root/)
  assert.doesNotMatch(result.stdout, /\.agents\/tasks/)
  assert.equal(await readFile(path.join(result.sandboxRoot, "output", "exit-status.txt"), "utf8"), "0\n")
})

test("orchestrator-until captures full task args before execution", async () => {
  const result = await runCli(["orchestrator-until", "planner", "make", "a", "plan"], { env: { OPENCODE_SANDBOX_STOP_PHASE: "before" } })
  assert.equal(result.status, 0, result.stderr)
  const marker = JSON.parse(await readFile(path.join(result.sandboxRoot, "output", "stop-marker.json"), "utf8"))
  assert.equal(marker.phase, "before")
  assert.equal(marker.subagent, "planner")
  assert.equal(marker.observedSubagent, "planner")
  assert.equal(marker.inputArgs.subagent_type, "planner")
  assert.equal(marker.inputArgs.prompt, highEntropyTaskPrompt)
  assert.notEqual(marker.inputArgs.prompt, "STALE-BEFORE-PROMPT")
  assert.ok(marker.inputArgs.prompt.length > 1200)
  assert.doesNotMatch(marker.inputArgs.prompt, /\.agents\/tasks/)
  assert.doesNotMatch(marker.inputArgs.prompt, /request\.md/)
  assert.doesNotMatch(marker.inputArgs.prompt, /NO_[A-Z_]*PLAN[A-Z_]*/)
})

test("orchestrator-until captures after execution args from input instead of stale hook output", async () => {
  const result = await runCli(["orchestrator-until", "planner", "make", "a", "plan"])
  assert.equal(result.status, 0, result.stderr)
  const marker = JSON.parse(await readFile(path.join(result.sandboxRoot, "output", "stop-marker.json"), "utf8"))
  assert.equal(marker.phase, "after")
  assert.equal(marker.subagent, "planner")
  assert.equal(marker.observedSubagent, "planner")
  assert.equal(marker.inputArgs.subagent_type, "planner")
  assert.equal(marker.inputArgs.prompt, highEntropyTaskPrompt)
  assert.notEqual(marker.inputArgs.prompt, "STALE-AFTER-PROMPT")
  assert.ok(marker.inputArgs.prompt.length > 1200)
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

test("orchestrator-final-check succeeds when approval is followed by read-only inspection and judgment", async () => {
  const result = await runCli(["orchestrator-final-check", "make", "a", "tiny", "change"], { fakeOptions: { events: "final-check-approved" } })
  assert.equal(result.status, 0, result.stderr)
  const marker = JSON.parse(await readFile(path.join(result.sandboxRoot, "output", "final-check-marker.json"), "utf8"))
  assert.equal(marker.reviewerApproved, true)
  assert.equal(marker.readOnlyToolAfterApproval, true)
  assert.equal(marker.firstReadOnlyToolAfterApproval.tool, "read")
  assert.match(result.stdout, /Final-check marker:/)
})

test("orchestrator-final-check fails without read-only inspection after approval", async () => {
  const result = await runCli(["orchestrator-final-check", "make", "a", "tiny", "change"], { fakeOptions: { events: "final-check-missing-read" } })
  assert.equal(result.status, 1)
  assert.match(result.stderr, /no read\/glob\/grep tool call observed after reviewer approval/)
})

test("orchestrator-final-check fails without orchestrator merge-readiness judgment", async () => {
  const result = await runCli(["orchestrator-final-check", "make", "a", "tiny", "change"], { fakeOptions: { events: "final-check-missing-judgment" } })
  assert.equal(result.status, 1)
  assert.match(result.stderr, /final response does not contain orchestrator merge-readiness judgment/)
})

test("orchestrator prompt requires direct final read-only merge-readiness judgment", async () => {
  const prompt = await readFile(path.join(repoOpencode, "agents", "orchestrator.md"), "utf8")
  assert.match(prompt, /After reviewer returns `verdict: APPROVED`/)
  assert.match(prompt, /Use read-only tools \(`read`, `glob`, and\/or `grep`\) yourself/)
  assert.match(prompt, /## Orchestrator Merge-Readiness Judgment/)
})
