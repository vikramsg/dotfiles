/**
 * OpenCode sandbox CLI for running real OpenCode in isolated sandbox flows.
 *
 * This exists to debug and test the orchestrator and individual agents without
 * touching the normal OpenCode config, data, cache, or state directories. Each
 * run creates isolated XDG homes under the sandbox root while preserving the
 * command, metadata, logs, raw events, and marker/status files for inspection.
 *
 * Usage from the repository root:
 *   just opencode-sandbox orchestrator-until <subagent> <prompt...>
 *   just opencode-sandbox single-agent <agent> <prompt...>
 *
 * Environment variables:
 *   OPENCODE_SANDBOX_ROOT       Override the sandbox root directory.
 *   OPENCODE_SANDBOX_MODEL      Override the model written to sandbox config.
 *   OPENCODE_SANDBOX_STOP_PHASE Stop before or after the target subagent
 *                               for orchestrator-until runs; defaults to after.
 */
import { spawn } from "node:child_process"
import { createWriteStream } from "node:fs"
import * as fs from "node:fs/promises"
import { existsSync, lstatSync, readlinkSync } from "node:fs"
import * as os from "node:os"
import * as path from "node:path"
import { fileURLToPath } from "node:url"

type SandboxPaths = {
  repoRoot: string
  opencodeRoot: string
  sourceConfig: string
  sandboxRoot: string
  configHome: string
  dataHome: string
  cacheHome: string
  stateHome: string
  opencodeConfigDir: string
  pluginDir: string
  worktree: string
  outputDir: string
  commandFile: string
  eventsFile: string
  logFile: string
  statusFile: string
  rawStatusFile: string
  metadataFile: string
  realDb: string
}

type EventValue = null | boolean | number | string | EventValue[] | { [key: string]: EventValue }

const usage = `Usage: sandbox-cli <subcommand> <args...>

Subcommands:
  orchestrator-until <subagent> <prompt...>
  single-agent <agent> <prompt...>`

function failUsage(message?: string): never {
  if (message) console.error(`error: ${message}`)
  console.error(usage)
  process.exit(64)
}

function repoRootFromImportMeta(): string {
  const thisFile = fileURLToPath(import.meta.url)
  return path.resolve(path.dirname(thisFile), "../../..")
}

async function commandExists(command: string): Promise<boolean> {
  const pathEnv = process.env.PATH || ""
  for (const dir of pathEnv.split(path.delimiter)) {
    if (!dir) continue
    const candidate = path.join(dir, command)
    try {
      await fs.access(candidate, fs.constants.X_OK)
      return true
    } catch {}
  }
  return false
}

async function makeSandboxPaths(): Promise<SandboxPaths> {
  const repoRoot = repoRootFromImportMeta()
  const opencodeRoot = path.join(repoRoot, "opencode")
  const sandboxRoot = process.env.OPENCODE_SANDBOX_ROOT || await fs.mkdtemp(path.join(os.tmpdir(), "opencode-sandbox-"))
  const configHome = path.join(sandboxRoot, "config")
  const dataHome = path.join(sandboxRoot, "data")
  const cacheHome = path.join(sandboxRoot, "cache")
  const stateHome = path.join(sandboxRoot, "state")
  const opencodeConfigDir = path.join(configHome, "opencode")
  const pluginDir = path.join(opencodeConfigDir, "plugins")
  const worktree = path.join(sandboxRoot, "worktree")
  const outputDir = path.join(sandboxRoot, "output")
  const userDataHome = path.join(process.env.XDG_DATA_HOME || path.join(os.homedir(), ".local", "share"), "opencode")

  await fs.mkdir(opencodeConfigDir, { recursive: true })
  await fs.mkdir(pluginDir, { recursive: true })
  await fs.mkdir(worktree, { recursive: true })
  await fs.mkdir(outputDir, { recursive: true })
  await fs.mkdir(dataHome, { recursive: true })
  await fs.mkdir(cacheHome, { recursive: true })
  await fs.mkdir(stateHome, { recursive: true })
  await copyAuthFiles(userDataHome, path.join(dataHome, "opencode"))

  return {
    repoRoot,
    opencodeRoot,
    sourceConfig: path.join(opencodeRoot, "opencode.json"),
    sandboxRoot,
    configHome,
    dataHome,
    cacheHome,
    stateHome,
    opencodeConfigDir,
    pluginDir,
    worktree,
    outputDir,
    commandFile: path.join(outputDir, "command.txt"),
    eventsFile: path.join(outputDir, "events.jsonl"),
    logFile: path.join(outputDir, "opencode.log"),
    statusFile: path.join(outputDir, "exit-status.txt"),
    rawStatusFile: path.join(outputDir, "opencode-exit-status.txt"),
    metadataFile: path.join(outputDir, "metadata.json"),
    realDb: path.join(userDataHome, "opencode.db"),
  }
}

async function copyAuthFiles(sourceDir: string, targetDir: string): Promise<void> {
  await fs.mkdir(targetDir, { recursive: true })
  for (const name of ["auth.json", "mcp-auth.json"]) {
    const source = path.join(sourceDir, name)
    const target = path.join(targetDir, name)
    if (existsSync(source) && !existsSync(target)) await fs.copyFile(source, target)
  }
}

async function linkRepoDir(source: string, target: string): Promise<void> {
  if (existsSync(target) || lstatExists(target)) {
    if (lstatSync(target).isSymbolicLink() && readlinkSync(target) === source) return
    throw new Error(`sandbox path already exists and is not the expected symlink: ${target}`)
  }
  await fs.symlink(source, target)
}

function lstatExists(file: string): boolean {
  try {
    lstatSync(file)
    return true
  } catch {
    return false
  }
}

async function symlinkAgentsIndividually(paths: SandboxPaths): Promise<void> {
  const sandboxAgentsDir = path.join(paths.opencodeConfigDir, "agents")
  await fs.mkdir(sandboxAgentsDir, { recursive: true })
  const agentsDir = path.join(paths.opencodeRoot, "agents")
  for (const entry of await fs.readdir(agentsDir)) {
    if (entry.endsWith(".md")) await linkRepoDir(path.join(agentsDir, entry), path.join(sandboxAgentsDir, entry))
  }
}

async function writeSandboxConfig(paths: SandboxPaths, plugin: string): Promise<void> {
  const config = JSON.parse(await fs.readFile(paths.sourceConfig, "utf8"))
  config.instructions = [path.join(paths.opencodeRoot, "rules.md")]
  config.model = process.env.OPENCODE_SANDBOX_MODEL || normalizeModel(config, config.model)
  config.plugin = (config.plugin || []).map((item: string) => item === "./plugins/orchestration-state.js"
    ? path.join(paths.opencodeRoot, "plugins", "orchestration-state.js")
    : item)
  config.plugin.push(plugin)
  await fs.writeFile(path.join(paths.opencodeConfigDir, "opencode.json"), `${JSON.stringify(config, null, 2)}\n`)
}

function normalizeModel(config: Record<string, any>, value: string): string {
  if (configuredModelExists(config, value)) return value
  const [providerID, modelID] = String(value || "").split("/")
  if (!providerID || !modelID) return value
  const candidate = `${providerID}/${modelID.replace(/-(\d+)$/, ".$1")}`
  return configuredModelExists(config, candidate) ? candidate : value
}

function configuredModelExists(config: Record<string, any>, value: string): boolean {
  const [providerID, modelID] = String(value || "").split("/")
  if (!providerID || !modelID) return true
  return Boolean(config.provider?.[providerID]?.models?.[modelID])
}

async function writeStopPlugin(file: string): Promise<void> {
  await fs.writeFile(file, `import fs from "node:fs"
import path from "node:path"

function getSubagent(input, hookOutput = null) {
  return input?.args?.subagent_type || input?.args?.subagentType || input?.args?.agent ||
    hookOutput?.args?.subagent_type || hookOutput?.args?.subagentType || hookOutput?.args?.agent || ""
}

function normalizeText(value) {
  if (typeof value === "string") return value
  if (value === undefined || value === null) return ""
  return JSON.stringify(value)
}

function preview(value, limit = 1200) {
  const text = normalizeText(value)
  return text.length <= limit ? text : \`\${text.slice(0, limit)}…\`
}

function writeStopMarker(payload) {
  const markerPath = process.env.OPENCODE_SANDBOX_STOP_MARKER
  if (!markerPath) return
  fs.mkdirSync(path.dirname(markerPath), { recursive: true })
  fs.writeFileSync(markerPath, \`\${JSON.stringify(payload, null, 2)}\n\`)
}

function stopNow({ phase, subagent, input, output = null, observedSubagent = subagent }) {
  const target = process.env.OPENCODE_SANDBOX_STOP_AT || ""
  writeStopMarker({
    stopped: true,
    phase,
    subagent,
    observedSubagent,
    target,
    callID: input.callID || null,
    title: output?.title || null,
    outputPreview: output ? preview(output.output) : null,
    stoppedAt: new Date().toISOString(),
  })
  throw new Error(\`OPENCODE_SANDBOX_STOP \${phase} \${subagent}\`)
}

function stopIfMatched(phase, input, output = null, hookOutput = null) {
  if (input?.tool !== "task") return
  const subagent = getSubagent(input, hookOutput)
  const target = process.env.OPENCODE_SANDBOX_STOP_AT || ""
  const expectedPhase = process.env.OPENCODE_SANDBOX_STOP_PHASE || "after"
  if (phase !== expectedPhase || subagent !== target) return
  stopNow({ phase, subagent, input, output })
}

export async function StopAtSubagentPlugin() {
  return {
    "tool.execute.before": async (input, output) => { stopIfMatched("before", input, null, output) },
    "tool.execute.after": async (input, output) => { stopIfMatched("after", input, output) },
  }
}
`)
}

async function writeObserverPlugin(file: string): Promise<void> {
  await fs.writeFile(file, `import fs from "node:fs"
import path from "node:path"

function getSubagent(input, hookOutput = null) {
  return input?.args?.subagent_type || input?.args?.subagentType || input?.args?.agent ||
    hookOutput?.args?.subagent_type || hookOutput?.args?.subagentType || hookOutput?.args?.agent || ""
}

function writeMarker(payload) {
  const markerPath = process.env.OPENCODE_SANDBOX_SINGLE_AGENT_MARKER
  if (!markerPath) return
  fs.mkdirSync(path.dirname(markerPath), { recursive: true })
  fs.writeFileSync(markerPath, \`\${JSON.stringify(payload, null, 2)}\n\`)
}

function observe(phase, input, output = null, hookOutput = null) {
  if (input?.tool !== "task") return
  const observedSubagent = getSubagent(input, hookOutput)
  const target = process.env.OPENCODE_SANDBOX_SINGLE_AGENT || ""
  if (observedSubagent !== target) return
  writeMarker({
    observed: true,
    phase,
    subagent: target,
    observedSubagent,
    callID: input.callID || null,
    title: output?.title || null,
    observedAt: new Date().toISOString(),
  })
}

export async function SingleAgentObserverPlugin() {
  return {
    "tool.execute.before": async (input, output) => { observe("before", input, null, output) },
    "tool.execute.after": async (input, output) => { observe("after", input, output) },
  }
}
`)
}

async function runOpencode(args: string[], env: NodeJS.ProcessEnv, paths: SandboxPaths, watchMarker?: string): Promise<number> {
  const stdout = createWriteStream(paths.eventsFile)
  const stderr = createWriteStream(paths.logFile)
  const child = spawn("opencode", args, { env: { ...process.env, ...env }, stdio: ["ignore", "pipe", "pipe"] })
  child.stdout.pipe(stdout)
  child.stderr.pipe(stderr)

  let watcher: NodeJS.Timeout | undefined
  if (watchMarker) {
    watcher = setInterval(() => {
      if (existsSync(watchMarker) && lstatSync(watchMarker).size > 0) {
        clearInterval(watcher)
        setTimeout(() => child.kill("SIGTERM"), 1000)
      }
    }, 200)
  }

  const status = await new Promise<number>((resolve) => {
    child.on("close", (code, signal) => resolve(closeStatus(code, signal)))
  })
  if (watcher) clearInterval(watcher)
  await Promise.all([new Promise((resolve) => stdout.end(resolve)), new Promise((resolve) => stderr.end(resolve))])
  return status
}

function closeStatus(code: number | null, signal: NodeJS.Signals | null): number {
  if (code !== null) return code
  if (!signal) return 1
  const signalNumber = (os.constants.signals as Record<string, number>)[signal]
  return typeof signalNumber === "number" ? 128 + signalNumber : 128
}

async function parseEvents(eventsPath: string): Promise<{ events: EventValue[], errors: string[] }> {
  const errors: string[] = []
  const events: EventValue[] = []
  try {
    const text = existsSync(eventsPath) ? await fs.readFile(eventsPath, "utf8") : ""
    for (const [index, line] of text.split(/\n/).entries()) {
      if (!line.trim()) continue
      try {
        events.push(JSON.parse(line) as EventValue)
      } catch (error) {
        errors.push(`events.jsonl line ${index + 1} is not valid JSON: ${(error as Error).message}`)
      }
    }
  } catch (error) {
    errors.push(`cannot read events.jsonl: ${(error as Error).message}`)
  }
  if (events.length < 2 || !events.some((event) => typeof event === "object" && event !== null && !Array.isArray(event) && event.type !== "step_start")) {
    errors.push("events.jsonl does not contain meaningful OpenCode events")
  }
  return { events, errors }
}

function containsValue(value: EventValue, expected: string): boolean {
  if (!expected) return false
  if (value === expected) return true
  if (Array.isArray(value)) return value.some((item) => containsValue(item, expected))
  if (value && typeof value === "object") return Object.values(value).some((item) => containsValue(item, expected))
  return false
}

async function commonValidation(paths: SandboxPaths): Promise<{ events: EventValue[], errors: string[] }> {
  const errors: string[] = []
  const log = existsSync(paths.logFile) ? await fs.readFile(paths.logFile, "utf8") : ""
  if (log.includes("Falling back to default agent")) errors.push("log contains default-agent fallback")
  if (log.includes(paths.realDb)) errors.push(`log contains user OpenCode database path: ${paths.realDb}`)
  const parsed = await parseEvents(paths.eventsFile)
  errors.push(...parsed.errors)
  return { events: parsed.events, errors }
}

async function validateOrchestrator(paths: SandboxPaths, markerPath: string, stopAt: string, stopPhase: string): Promise<boolean> {
  const { events, errors } = await commonValidation(paths)
  if (!existsSync(markerPath)) {
    errors.push("stop marker was not written")
  } else {
    try {
      const marker = JSON.parse(await fs.readFile(markerPath, "utf8"))
      if (marker.phase !== stopPhase) errors.push(`stop marker phase ${marker.phase || "<missing>"}, expected ${stopPhase}`)
      if (marker.subagent !== stopAt) errors.push(`stop marker subagent ${marker.subagent || "<missing>"}, expected ${stopAt}`)
      if (marker.observedSubagent !== stopAt) errors.push(`stop marker observed ${marker.observedSubagent || "<missing>"}, expected ${stopAt}`)
      if (!marker.callID) errors.push("stop marker callID is missing")
      else if (!events.some((event) => containsValue(event, marker.callID))) errors.push(`stop marker callID ${marker.callID} was not found in current events.jsonl`)
    } catch (error) {
      errors.push(`stop marker is not valid JSON: ${(error as Error).message}`)
    }
  }
  for (const error of errors) console.error(`validation error: ${error}`)
  return errors.length === 0
}

async function validateSingle(paths: SandboxPaths, markerPath: string, agent: string, agentMode: string): Promise<boolean> {
  const { events, errors } = await commonValidation(paths)
  if (agentMode === "subagent") {
    if (!existsSync(markerPath)) {
      errors.push("single-agent marker was not written")
    } else {
      try {
        const marker = JSON.parse(await fs.readFile(markerPath, "utf8"))
        if (marker.observedSubagent !== agent) errors.push(`single-agent marker observed ${marker.observedSubagent || "<missing>"}, expected ${agent}`)
        if (!marker.callID) errors.push("single-agent marker callID is missing")
        else if (!events.some((event) => containsValue(event, marker.callID))) errors.push(`single-agent marker callID ${marker.callID} was not found in current events.jsonl`)
      } catch (error) {
        errors.push(`single-agent marker is not valid JSON: ${(error as Error).message}`)
      }
    }
  }
  for (const error of errors) console.error(`validation error: ${error}`)
  return errors.length === 0
}

async function hasEventError(eventsPath: string): Promise<boolean> {
  const text = existsSync(eventsPath) ? await fs.readFile(eventsPath, "utf8") : ""
  for (const line of text.split(/\n+/)) {
    if (!line.trim()) continue
    try {
      if (JSON.parse(line).type === "error") return true
    } catch {}
  }
  return false
}

async function cleanupKnownFiles(files: string[]): Promise<void> {
  await Promise.all(files.map((file) => fs.rm(file, { force: true }).catch(() => undefined)))
}

function shellQuote(value: string): string {
  return `'${value.replaceAll("'", `'\\''`)}'`
}

async function runOrchestratorUntil(args: string[]): Promise<number> {
  if (args.length < 2) failUsage()
  const [stopAt, ...promptParts] = args
  const prompt = promptParts.join(" ")
  const stopPhase = process.env.OPENCODE_SANDBOX_STOP_PHASE || "after"
  if (stopPhase !== "after" && stopPhase !== "before") failUsage('OPENCODE_SANDBOX_STOP_PHASE must be "after" or "before"')
  if (!await commandExists("opencode")) {
    console.error("error: opencode CLI was not found on PATH")
    return 127
  }

  const paths = await makeSandboxPaths()
  const stopPlugin = path.join(paths.pluginDir, "stop-at-subagent.js")
  const stopMarker = path.join(paths.outputDir, "stop-marker.json")
  await linkRepoDir(path.join(paths.opencodeRoot, "agents"), path.join(paths.opencodeConfigDir, "agents"))
  await linkRepoDir(path.join(paths.opencodeRoot, "commands"), path.join(paths.opencodeConfigDir, "commands"))
  await writeStopPlugin(stopPlugin)
  await writeSandboxConfig(paths, stopPlugin)
  await cleanupKnownFiles([stopMarker, paths.statusFile, paths.rawStatusFile])
  await fs.writeFile(paths.commandFile, `XDG_CONFIG_HOME=${shellQuote(paths.configHome)} XDG_DATA_HOME=${shellQuote(paths.dataHome)} XDG_CACHE_HOME=${shellQuote(paths.cacheHome)} XDG_STATE_HOME=${shellQuote(paths.stateHome)} OPENCODE_SANDBOX_STOP_AT=${shellQuote(stopAt)} OPENCODE_SANDBOX_STOP_PHASE=${shellQuote(stopPhase)} OPENCODE_SANDBOX_STOP_MARKER=${shellQuote(stopMarker)} opencode run --dir ${shellQuote(paths.worktree)} --command orchestrate --format json --print-logs --log-level DEBUG ${shellQuote(prompt)}\n`)
  await fs.writeFile(paths.metadataFile, `${JSON.stringify({ sandboxRoot: paths.sandboxRoot, configHome: paths.configHome, dataHome: paths.dataHome, cacheHome: paths.cacheHome, stateHome: paths.stateHome, worktree: paths.worktree, outputDir: paths.outputDir, stopAt, stopPhase, prompt, stopPlugin, stopMarker, stateRoot: path.join(paths.worktree, ".agents", "tasks"), generatedAt: new Date().toISOString() }, null, 2)}\n`)

  const rawStatus = await runOpencode(["run", "--dir", paths.worktree, "--command", "orchestrate", "--format", "json", "--print-logs", "--log-level", "DEBUG", prompt], {
    XDG_CONFIG_HOME: paths.configHome,
    XDG_DATA_HOME: paths.dataHome,
    XDG_CACHE_HOME: paths.cacheHome,
    XDG_STATE_HOME: paths.stateHome,
    OPENCODE_SANDBOX_STOP_AT: stopAt,
    OPENCODE_SANDBOX_STOP_PHASE: stopPhase,
    OPENCODE_SANDBOX_STOP_MARKER: stopMarker,
  }, paths, stopMarker)
  const validationOk = await validateOrchestrator(paths, stopMarker, stopAt, stopPhase)
  const status = existsSync(stopMarker) && validationOk ? 0 : 1
  await writeStatuses(paths, rawStatus, status)
  printOrchestratorSummary(paths, stopPlugin, stopMarker, rawStatus, status)
  return status
}

async function runSingleAgent(args: string[]): Promise<number> {
  if (args.length < 2) failUsage()
  const [agentName, ...promptParts] = args
  const prompt = promptParts.join(" ")
  if (!await commandExists("opencode")) {
    console.error("error: opencode CLI was not found on PATH")
    return 127
  }

  const paths = await makeSandboxPaths()
  const observerPlugin = path.join(paths.pluginDir, "single-agent-observer.js")
  const marker = path.join(paths.outputDir, "single-agent-marker.json")
  await symlinkAgentsIndividually(paths)
  await linkRepoDir(path.join(paths.opencodeRoot, "commands"), path.join(paths.opencodeConfigDir, "commands"))
  const agentFile = path.join(paths.opencodeConfigDir, "agents", `${agentName}.md`)
  if (!existsSync(agentFile)) {
    console.error(`error: agent file was not found in sandbox config: ${agentFile}`)
    return 66
  }
  const agentMode = parseAgentMode(await fs.readFile(agentFile, "utf8"))
  let runAgent = agentName
  let runPrompt = prompt
  if (agentMode === "subagent") {
    runAgent = "sandbox-single-agent-harness"
    await fs.writeFile(path.join(paths.opencodeConfigDir, "agents", "sandbox-single-agent-harness.md"), harnessAgent())
    runPrompt = `Requested subagent: ${agentName}\n\nUser prompt:\n${prompt}`
  }
  await writeObserverPlugin(observerPlugin)
  await writeSandboxConfig(paths, observerPlugin)
  await cleanupKnownFiles([marker, paths.statusFile, paths.rawStatusFile])
  await fs.writeFile(paths.commandFile, `XDG_CONFIG_HOME=${shellQuote(paths.configHome)} XDG_DATA_HOME=${shellQuote(paths.dataHome)} XDG_CACHE_HOME=${shellQuote(paths.cacheHome)} XDG_STATE_HOME=${shellQuote(paths.stateHome)} OPENCODE_SANDBOX_SINGLE_AGENT=${shellQuote(agentName)} OPENCODE_SANDBOX_SINGLE_AGENT_MARKER=${shellQuote(marker)} opencode run --dir ${shellQuote(paths.worktree)} --agent ${shellQuote(runAgent)} --format json --print-logs --log-level DEBUG ${shellQuote(runPrompt)}\n`)
  await fs.writeFile(paths.metadataFile, `${JSON.stringify({ sandboxRoot: paths.sandboxRoot, configHome: paths.configHome, dataHome: paths.dataHome, cacheHome: paths.cacheHome, stateHome: paths.stateHome, worktree: paths.worktree, outputDir: paths.outputDir, agent: agentName, agentMode, runAgent, prompt, observerPlugin, singleAgentMarker: marker, generatedAt: new Date().toISOString() }, null, 2)}\n`)
  const rawStatus = await runOpencode(["run", "--dir", paths.worktree, "--agent", runAgent, "--format", "json", "--print-logs", "--log-level", "DEBUG", runPrompt], {
    XDG_CONFIG_HOME: paths.configHome,
    XDG_DATA_HOME: paths.dataHome,
    XDG_CACHE_HOME: paths.cacheHome,
    XDG_STATE_HOME: paths.stateHome,
    OPENCODE_SANDBOX_SINGLE_AGENT: agentName,
    OPENCODE_SANDBOX_SINGLE_AGENT_MARKER: marker,
  }, paths)
  let status = rawStatus
  if (status === 0 && await hasEventError(paths.eventsFile)) status = 1
  if (!await validateSingle(paths, marker, agentName, agentMode)) status = 1
  await writeStatuses(paths, rawStatus, status)
  printSingleSummary(paths, observerPlugin, marker, rawStatus, status)
  return status
}

function parseAgentMode(text: string): string {
  const frontmatter = text.match(/^---\n([\s\S]*?)\n---/)?.[1] || ""
  return frontmatter.match(/^mode:\s*([^\n#]+)/m)?.[1]?.trim() || "primary"
}

function harnessAgent(): string {
  return `---
description: Sandbox-only primary harness that calls exactly one requested real subagent.
mode: primary
hidden: true
steps: 8
permission:
  bash: deny
  edit: deny
  write: deny
  todowrite: deny
  task:
    planner: allow
    implementer: allow
    reviewer: allow
---
# Sandbox Single-Agent Harness

Use the task tool exactly once for the requested subagent. Do not call any other tools.
Return the subagent output and nothing else.
`
}

async function writeStatuses(paths: SandboxPaths, rawStatus: number, status: number): Promise<void> {
  await fs.writeFile(paths.statusFile, `${status}\n`)
  await fs.writeFile(paths.rawStatusFile, `${rawStatus}\n`)
}

function printOrchestratorSummary(paths: SandboxPaths, stopPlugin: string, stopMarker: string, rawStatus: number, status: number): void {
  console.log(`Sandbox root: ${paths.sandboxRoot}`)
  console.log(`Worktree: ${paths.worktree}`)
  console.log(`Generated config: ${path.join(paths.opencodeConfigDir, "opencode.json")}`)
  console.log(`Generated stop plugin: ${stopPlugin}`)
  console.log(`Command: ${paths.commandFile}`)
  console.log(`Metadata: ${paths.metadataFile}`)
  console.log(`Logs: ${paths.logFile}`)
  console.log(`Raw events: ${paths.eventsFile}`)
  console.log(`Stop marker: ${stopMarker}`)
  console.log(`Persistent state root: ${path.join(paths.worktree, ".agents", "tasks")}`)
  console.log(`OpenCode CLI exit status: ${paths.rawStatusFile} (${rawStatus})`)
  console.log(`Script exit status: ${paths.statusFile} (${status})`)
}

function printSingleSummary(paths: SandboxPaths, observerPlugin: string, marker: string, rawStatus: number, status: number): void {
  console.log(`Sandbox root: ${paths.sandboxRoot}`)
  console.log(`Worktree: ${paths.worktree}`)
  console.log(`Generated config: ${path.join(paths.opencodeConfigDir, "opencode.json")}`)
  console.log(`Generated observer plugin: ${observerPlugin}`)
  console.log(`Command: ${paths.commandFile}`)
  console.log(`Metadata: ${paths.metadataFile}`)
  console.log(`Logs: ${paths.logFile}`)
  console.log(`Raw events: ${paths.eventsFile}`)
  console.log(`Single-agent marker: ${marker}`)
  console.log(`OpenCode CLI exit status: ${paths.rawStatusFile} (${rawStatus})`)
  console.log(`Script exit status: ${paths.statusFile} (${status})`)
}

async function main(): Promise<number> {
  const [subcommand, ...args] = process.argv.slice(2)
  if (!subcommand) failUsage()
  try {
    if (subcommand === "orchestrator-until") return await runOrchestratorUntil(args)
    if (subcommand === "single-agent") return await runSingleAgent(args)
    failUsage(`unknown subcommand: ${subcommand}`)
  } catch (error) {
    console.error(`error: ${(error as Error).message}`)
    return 1
  }
}

process.exitCode = await main()
