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
 *   just opencode-sandbox orchestrator-final-check <prompt...>
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

type FinalCheckToolCall = {
  tool: string
  callID: string | null
  args: Record<string, unknown> | null
  observedAt: string
  observedSequence?: number
}

const usage = `Usage: sandbox-cli <subcommand> <args...>

Subcommands:
  orchestrator-until <subagent> <prompt...>
  orchestrator-final-check <prompt...>
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

function actualArgsForPhase(phase, input, hookOutput = null) {
  if (phase === "before") return hookOutput?.args ?? input?.args ?? null
  return input?.args ?? hookOutput?.args ?? null
}

function getSubagent(args) {
  return args?.subagent_type || args?.subagentType || args?.agent || ""
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

function stopNow({ phase, subagent, input, output = null, observedSubagent = subagent, inputArgs = null }) {
  const target = process.env.OPENCODE_SANDBOX_STOP_AT || ""
  writeStopMarker({
    stopped: true,
    phase,
    subagent,
    observedSubagent,
    target,
    callID: input.callID || null,
    inputArgs,
    title: output?.title || null,
    outputPreview: output ? preview(output.output) : null,
    stoppedAt: new Date().toISOString(),
  })
  throw new Error(\`OPENCODE_SANDBOX_STOP \${phase} \${subagent}\`)
}

function stopIfMatched(phase, input, output = null, hookOutput = null) {
  if (input?.tool !== "task") return
  const actualArgs = actualArgsForPhase(phase, input, hookOutput)
  const subagent = getSubagent(actualArgs)
  const target = process.env.OPENCODE_SANDBOX_STOP_AT || ""
  const expectedPhase = process.env.OPENCODE_SANDBOX_STOP_PHASE || "after"
  if (phase !== expectedPhase || subagent !== target) return
  stopNow({ phase, subagent, input, output, inputArgs: actualArgs })
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

async function writeFinalCheckPlugin(file: string): Promise<void> {
  await fs.writeFile(file, `import fs from "node:fs"
import path from "node:path"

const readOnlyTools = new Set(["read", "glob", "grep"])
const state = {
  sequence: 0,
  reviewerApproved: false,
  reviewerApprovalCallID: null,
  reviewerApprovalObservedAt: null,
  latestReviewerApprovalSequence: null,
  readOnlyToolAfterApproval: false,
  firstReadOnlyToolAfterApproval: null,
  readOnlyToolsAfterApproval: [],
  postApprovalLoopReentry: false,
  postApprovalLoopSubagents: [],
}

function getSubagent(args) {
  return args?.subagent_type || args?.subagentType || args?.agent || ""
}

function normalizeText(value) {
  if (typeof value === "string") return value
  if (value === undefined || value === null) return ""
  return JSON.stringify(value)
}

function hasReviewerApproval(output) {
  const text = normalizeText(output?.output ?? output)
  return /verdict:\\s*APPROVED\\b/i.test(text)
}

function nextSequence() {
  state.sequence += 1
  return state.sequence
}

function writeMarker() {
  const markerPath = process.env.OPENCODE_SANDBOX_FINAL_CHECK_MARKER
  if (!markerPath) return
  fs.mkdirSync(path.dirname(markerPath), { recursive: true })
  fs.writeFileSync(markerPath, \`\${JSON.stringify(state, null, 2)}\n\`)
}

function observe(input, output = null) {
  const observedSequence = nextSequence()
  const tool = input?.tool || ""
  if (tool === "task") {
    const subagent = getSubagent(input?.args)
    if (subagent === "reviewer" && hasReviewerApproval(output)) {
      state.reviewerApproved = true
      state.reviewerApprovalCallID = input.callID || null
      state.reviewerApprovalObservedAt = new Date().toISOString()
      state.latestReviewerApprovalSequence = observedSequence
      writeMarker()
      return
    }
    if (state.reviewerApproved && ["planner", "implementer", "reviewer"].includes(subagent)) {
      state.postApprovalLoopReentry = true
      state.postApprovalLoopSubagents.push({ subagent, callID: input.callID || null, observedAt: new Date().toISOString(), observedSequence })
      writeMarker()
    }
    return
  }
  if (state.reviewerApproved && readOnlyTools.has(tool)) {
    const call = { tool, callID: input.callID || null, args: input.args || null, observedAt: new Date().toISOString(), observedSequence }
    state.readOnlyToolAfterApproval = true
    state.readOnlyToolsAfterApproval.push(call)
    if (!state.firstReadOnlyToolAfterApproval) {
      state.firstReadOnlyToolAfterApproval = call
    }
    writeMarker()
  }
}

export async function FinalCheckObserverPlugin() {
  writeMarker()
  return {
    "tool.execute.after": async (input, output) => { observe(input, output) },
  }
}
`)
}

async function runOpencode(args: string[], env: NodeJS.ProcessEnv, paths: SandboxPaths, watchMarker?: string): Promise<number> {
  const stdout = createWriteStream(paths.eventsFile)
  const stderr = createWriteStream(paths.logFile)
  const child = spawn("opencode", args, { env: { ...process.env, ...env }, stdio: ["ignore", "pipe", "pipe"], detached: process.platform !== "win32" })
  child.stdout.pipe(stdout)
  child.stderr.pipe(stderr)

  let watcher: NodeJS.Timeout | undefined
  let delayedSigtermTimer: NodeJS.Timeout | undefined
  let killTimer: NodeJS.Timeout | undefined
  if (watchMarker) {
    watcher = setInterval(() => {
      if (existsSync(watchMarker) && lstatSync(watchMarker).size > 0) {
        clearInterval(watcher)
        delayedSigtermTimer = setTimeout(() => {
          signalProcessGroup(child.pid, "SIGTERM")
          killTimer = setTimeout(() => signalProcessGroup(child.pid, "SIGKILL"), 5000)
        }, 1000)
      }
    }, 200)
  }

  const status = await new Promise<number>((resolve) => {
    child.on("close", (code, signal) => resolve(closeStatus(code, signal)))
  })
  if (watcher) clearInterval(watcher)
  if (delayedSigtermTimer) clearTimeout(delayedSigtermTimer)
  if (killTimer) clearTimeout(killTimer)
  await Promise.all([new Promise((resolve) => stdout.end(resolve)), new Promise((resolve) => stderr.end(resolve))])
  return status
}

function signalProcessGroup(pid: number | undefined, signal: NodeJS.Signals): void {
  if (!pid) return
  try {
    process.kill(process.platform === "win32" ? pid : -pid, signal)
  } catch {
    try {
      process.kill(pid, signal)
    } catch {}
  }
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

function containsTextMatching(value: EventValue, pattern: RegExp): boolean {
  if (typeof value === "string") return pattern.test(value)
  if (Array.isArray(value)) return value.some((item) => containsTextMatching(item, pattern))
  if (value && typeof value === "object") return Object.values(value).some((item) => containsTextMatching(item, pattern))
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

async function collectKnownWorktreeFiles(root: string): Promise<string[]> {
  const files: string[] = []
  async function visit(dir: string): Promise<void> {
    let entries
    try {
      entries = await fs.readdir(dir, { withFileTypes: true })
    } catch {
      return
    }
    for (const entry of entries) {
      const candidate = path.join(dir, entry.name)
      if (entry.isDirectory()) await visit(candidate)
      else if (entry.isFile()) files.push(path.resolve(candidate))
    }
  }
  await visit(root)
  return files
}

function normalizedTrustedOwner(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null
}

function trustedOwnerFromCorrelatedEvent(event: EventValue): string | null {
  if (!event || typeof event !== "object" || Array.isArray(event)) return null
  const record = event as Record<string, EventValue>
  return normalizedTrustedOwner(record.agent) || normalizedTrustedOwner(record.agentID) || normalizedTrustedOwner(record.agentId)
}

function eventMessageID(event: EventValue): string | null {
  if (!event || typeof event !== "object" || Array.isArray(event)) return null
  const record = event as Record<string, EventValue>
  const direct = normalizedTrustedOwner(record.messageID) || normalizedTrustedOwner(record.messageId)
  if (direct) return direct
  const part = record.part
  if (!part || typeof part !== "object" || Array.isArray(part)) return null
  const partRecord = part as Record<string, EventValue>
  return normalizedTrustedOwner(partRecord.messageID) || normalizedTrustedOwner(partRecord.messageId)
}

function parseLogMessageAgents(log: string): Map<string, string> {
  const owners = new Map<string, string>()
  let pending: { sessionID: string, messageID: string } | null = null
  for (const line of log.split(/\n/)) {
    const processorMatch = line.match(/\bservice=session\.processor\b.*\bsession\.id=([^\s]+).*\bmessageID=([^\s]+)\b/) ||
      line.match(/\bservice=session\.processor\b.*\bmessageID=([^\s]+).*\bsession\.id=([^\s]+)\b/)
    if (processorMatch) {
      pending = processorMatch[0].includes("session.id=") && processorMatch[0].indexOf("session.id=") < processorMatch[0].indexOf("messageID=")
        ? { sessionID: processorMatch[1], messageID: processorMatch[2] }
        : { sessionID: processorMatch[2], messageID: processorMatch[1] }
      continue
    }
    if (!pending) continue
    if (line.includes("service=session.processor")) {
      pending = null
      continue
    }
    const llmMatch = line.match(/\bservice=llm\b.*\bsession\.id=([^\s]+).*\bagent=([^\s]+)\b/) ||
      line.match(/\bservice=llm\b.*\bagent=([^\s]+).*\bsession\.id=([^\s]+)\b/)
    if (!llmMatch) continue
    const sessionIDFirst = llmMatch[0].indexOf("session.id=") < llmMatch[0].indexOf("agent=")
    const sessionID = sessionIDFirst ? llmMatch[1] : llmMatch[2]
    const agent = sessionIDFirst ? llmMatch[2] : llmMatch[1]
    if (sessionID === pending.sessionID) owners.set(pending.messageID, agent)
    pending = null
  }
  return owners
}

function trustedOwnerForCall(events: EventValue[], callID: string | null, logMessageAgents: Map<string, string>): string | null {
  if (!callID) return null
  let owner: string | null = null
  for (const event of events) {
    if (!containsValue(event, callID)) continue
    const eventOwner = trustedOwnerFromCorrelatedEvent(event)
    if (eventOwner) owner = eventOwner
    const messageID = eventMessageID(event)
    if (!owner && messageID) owner = logMessageAgents.get(messageID) || null
  }
  return owner
}

function isOrchestratorOwned(call: FinalCheckToolCall, events: EventValue[], logMessageAgents: Map<string, string>): boolean {
  return trustedOwnerForCall(events, call.callID, logMessageAgents) === "orchestrator"
}

function isInsideDirectory(candidate: string, root: string): boolean {
  const relative = path.relative(path.resolve(root), path.resolve(candidate))
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative))
}

function stringArg(args: Record<string, unknown> | null, name: string): string | null {
  const value = args?.[name]
  return typeof value === "string" && value.trim() ? value : null
}

function stringArgs(args: Record<string, unknown> | null, names: string[]): string[] {
  return names.flatMap((name) => {
    const value = stringArg(args, name)
    return value ? [value] : []
  })
}

const forbiddenArtifactNames = new Set([
  "request.md",
  "state.json",
  "plan.md",
  "review.md",
  "verification.md",
])

function isForbiddenFinalCheckTarget(candidate: string): boolean {
  const normalized = candidate.replaceAll("\\", "/")
  if (normalized.split("/").includes(".agents") && normalized.split("/").includes("tasks")) return true
  const basename = path.posix.basename(normalized)
  if (forbiddenArtifactNames.has(basename)) return true
  return [...forbiddenArtifactNames].some((name) => normalized.endsWith(`/${name}`))
}

function isRelatedPath(candidate: string, worktree: string, knownWorktreeFiles: string[]): boolean {
  if (isForbiddenFinalCheckTarget(candidate)) return false
  if (candidate.startsWith("~")) return false
  const resolved = path.isAbsolute(candidate) ? path.resolve(candidate) : path.resolve(worktree, candidate)
  return isInsideDirectory(resolved, worktree) || knownWorktreeFiles.includes(resolved)
}

function isKnownWorktreeFileTarget(candidate: string, worktree: string, knownWorktreeFiles: string[]): boolean {
  if (isForbiddenFinalCheckTarget(candidate)) return false
  if (candidate.startsWith("~")) return false
  const resolved = path.isAbsolute(candidate) ? path.resolve(candidate) : path.resolve(worktree, candidate)
  return knownWorktreeFiles.includes(resolved)
}

function isRelatedToWorktree(call: FinalCheckToolCall, worktree: string, knownWorktreeFiles: string[]): boolean {
  if (call.tool === "read") {
    const target = stringArg(call.args, "filePath") || stringArg(call.args, "path")
    return Boolean(target && isKnownWorktreeFileTarget(target, worktree, knownWorktreeFiles))
  }
  if (call.tool === "glob" || call.tool === "grep") {
    const targetArgNames = call.tool === "glob" ? ["path", "pattern"] : ["path", "include"]
    if (stringArgs(call.args, targetArgNames).some(isForbiddenFinalCheckTarget)) return false
    const basePath = stringArg(call.args, "path")
    if (basePath) return isRelatedPath(basePath, worktree, knownWorktreeFiles)
    const pattern = stringArg(call.args, "pattern")
    return Boolean(pattern && isRelatedPath(pattern, worktree, knownWorktreeFiles))
  }
  return false
}

function finalCheckToolCalls(marker: Record<string, any>): FinalCheckToolCall[] {
  const calls = Array.isArray(marker.readOnlyToolsAfterApproval) ? marker.readOnlyToolsAfterApproval : []
  if (calls.length > 0) return calls
  return marker.firstReadOnlyToolAfterApproval ? [marker.firstReadOnlyToolAfterApproval] : []
}

function finalResponseEvents(events: EventValue[]): EventValue[] {
  return events.filter((event) => {
    if (!event || typeof event !== "object" || Array.isArray(event)) return false
    if (event.role === "assistant") return true
    return event.type === "assistant" || event.type === "text" || (event.type === "message" && event.role !== "user")
  })
}

function finalAssistantResponse(events: EventValue[]): EventValue | null {
  const responses = finalResponseEvents(events)
  return responses.length > 0 ? responses[responses.length - 1] : null
}

function explicitMergeReadiness(event: EventValue): "YES" | "NO" | null {
  let last: "YES" | "NO" | null = null
  const visit = (value: EventValue): void => {
    if (typeof value === "string") {
      for (const match of value.matchAll(/merge_ready\s*:\s*(YES|NO)\b/gi)) last = match[1].toUpperCase() as "YES" | "NO"
      return
    }
    if (Array.isArray(value)) {
      for (const item of value) visit(item)
      return
    }
    if (value && typeof value === "object") for (const item of Object.values(value)) visit(item)
  }
  visit(event)
  return last
}

async function validateFinalCheck(paths: SandboxPaths, markerPath: string): Promise<boolean> {
  const { events, errors } = await commonValidation(paths)
  const log = existsSync(paths.logFile) ? await fs.readFile(paths.logFile, "utf8") : ""
  const logMessageAgents = parseLogMessageAgents(log)
  const knownWorktreeFiles = await collectKnownWorktreeFiles(paths.worktree)
  const finalResponse = finalAssistantResponse(events)
  if (!existsSync(markerPath)) {
    errors.push("final-check marker was not written")
  } else {
    try {
      const marker = JSON.parse(await fs.readFile(markerPath, "utf8"))
      if (marker.reviewerApproved !== true) errors.push("reviewer approval was not observed")
      if (marker.readOnlyToolAfterApproval !== true) errors.push("no read/glob/grep tool call observed after reviewer approval")
      const calls = finalCheckToolCalls(marker)
      const unexpectedTool = calls.find((call) => !["read", "glob", "grep"].includes(call.tool))?.tool
      if (marker.readOnlyToolAfterApproval === true && unexpectedTool) errors.push(`unexpected read-only tool marker: ${unexpectedTool}`)
      const latestApprovalSequence = typeof marker.latestReviewerApprovalSequence === "number" ? marker.latestReviewerApprovalSequence : null
      const callsAfterLatestApproval = latestApprovalSequence === null
        ? calls
        : calls.filter((call) => typeof call.observedSequence === "number" && call.observedSequence > latestApprovalSequence)
      const qualifyingCall = callsAfterLatestApproval.find((call) => isOrchestratorOwned(call, events, logMessageAgents) && isRelatedToWorktree(call, paths.worktree, knownWorktreeFiles))
      if (marker.readOnlyToolAfterApproval === true && latestApprovalSequence !== null && callsAfterLatestApproval.length === 0) {
        errors.push("no orchestrator-owned read/glob/grep tool call inspected sandbox worktree changes after latest reviewer approval")
      } else if (marker.readOnlyToolAfterApproval === true && !qualifyingCall) {
        if (!callsAfterLatestApproval.some((call) => trustedOwnerForCall(events, call.callID, logMessageAgents))) {
          errors.push("read/glob/grep ownership could not be validated from trusted runtime data after reviewer approval")
        }
        errors.push("no orchestrator-owned read/glob/grep tool call inspected sandbox worktree changes after reviewer approval")
      }
    } catch (error) {
      errors.push(`final-check marker is not valid JSON: ${(error as Error).message}`)
    }
  }
  if (!finalResponse || !containsTextMatching(finalResponse, /Orchestrator Merge-Readiness Judgment/i)) {
    errors.push("final response does not contain orchestrator merge-readiness judgment")
  }
  const mergeReady = finalResponse ? explicitMergeReadiness(finalResponse) : null
  if (!mergeReady) errors.push("final response missing explicit merge-readiness judgment: merge_ready: YES or merge_ready: NO")
  else if (mergeReady === "NO") errors.push("final explicit merge-readiness judgment is merge_ready: NO")
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
  await fs.writeFile(paths.metadataFile, `${JSON.stringify({ sandboxRoot: paths.sandboxRoot, configHome: paths.configHome, dataHome: paths.dataHome, cacheHome: paths.cacheHome, stateHome: paths.stateHome, worktree: paths.worktree, outputDir: paths.outputDir, stopAt, stopPhase, prompt, stopPlugin, stopMarker, generatedAt: new Date().toISOString() }, null, 2)}\n`)
  printStartupSummary("orchestrator-until", paths, [
    ["Generated stop plugin", stopPlugin],
    ["Stop target", stopAt],
    ["Stop phase", stopPhase],
    ["Stop marker", stopMarker],
  ])

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

async function runOrchestratorFinalCheck(args: string[]): Promise<number> {
  if (args.length < 1) failUsage()
  const prompt = args.join(" ")
  if (!await commandExists("opencode")) {
    console.error("error: opencode CLI was not found on PATH")
    return 127
  }

  const paths = await makeSandboxPaths()
  const observerPlugin = path.join(paths.pluginDir, "final-check-observer.js")
  const marker = path.join(paths.outputDir, "final-check-marker.json")
  await linkRepoDir(path.join(paths.opencodeRoot, "agents"), path.join(paths.opencodeConfigDir, "agents"))
  await linkRepoDir(path.join(paths.opencodeRoot, "commands"), path.join(paths.opencodeConfigDir, "commands"))
  await writeFinalCheckPlugin(observerPlugin)
  await writeSandboxConfig(paths, observerPlugin)
  await cleanupKnownFiles([marker, paths.statusFile, paths.rawStatusFile])
  await fs.writeFile(paths.commandFile, `XDG_CONFIG_HOME=${shellQuote(paths.configHome)} XDG_DATA_HOME=${shellQuote(paths.dataHome)} XDG_CACHE_HOME=${shellQuote(paths.cacheHome)} XDG_STATE_HOME=${shellQuote(paths.stateHome)} OPENCODE_SANDBOX_FINAL_CHECK_MARKER=${shellQuote(marker)} opencode run --dir ${shellQuote(paths.worktree)} --command orchestrate --format json --print-logs --log-level DEBUG ${shellQuote(prompt)}\n`)
  await fs.writeFile(paths.metadataFile, `${JSON.stringify({ sandboxRoot: paths.sandboxRoot, configHome: paths.configHome, dataHome: paths.dataHome, cacheHome: paths.cacheHome, stateHome: paths.stateHome, worktree: paths.worktree, outputDir: paths.outputDir, prompt, observerPlugin, finalCheckMarker: marker, generatedAt: new Date().toISOString() }, null, 2)}\n`)
  printStartupSummary("orchestrator-final-check", paths, [
    ["Generated observer plugin", observerPlugin],
    ["Final-check marker", marker],
  ])

  const rawStatus = await runOpencode(["run", "--dir", paths.worktree, "--command", "orchestrate", "--format", "json", "--print-logs", "--log-level", "DEBUG", prompt], {
    XDG_CONFIG_HOME: paths.configHome,
    XDG_DATA_HOME: paths.dataHome,
    XDG_CACHE_HOME: paths.cacheHome,
    XDG_STATE_HOME: paths.stateHome,
    OPENCODE_SANDBOX_FINAL_CHECK_MARKER: marker,
  }, paths)
  let status = rawStatus
  if (status === 0 && await hasEventError(paths.eventsFile)) status = 1
  if (!await validateFinalCheck(paths, marker)) status = 1
  await writeStatuses(paths, rawStatus, status)
  printFinalCheckSummary(paths, observerPlugin, marker, rawStatus, status)
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
  printStartupSummary("single-agent", paths, [
    ["Generated observer plugin", observerPlugin],
    ["Agent", agentName],
    ["Agent mode", agentMode],
    ["Run agent", runAgent],
    ["Single-agent marker", marker],
  ])
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

function printStartupSummary(subcommand: string, paths: SandboxPaths, details: [string, string][]): void {
  console.log(`Starting OpenCode sandbox: ${subcommand}`)
  console.log(`Sandbox root: ${paths.sandboxRoot}`)
  console.log(`Worktree: ${paths.worktree}`)
  console.log(`Generated config: ${path.join(paths.opencodeConfigDir, "opencode.json")}`)
  console.log(`Output dir: ${paths.outputDir}`)
  console.log(`Command: ${paths.commandFile}`)
  console.log(`Metadata: ${paths.metadataFile}`)
  console.log(`Logs: ${paths.logFile}`)
  console.log(`Raw events: ${paths.eventsFile}`)
  for (const [label, value] of details) console.log(`${label}: ${value}`)
  console.log("Running OpenCode...")
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
  console.log(`OpenCode CLI exit status: ${paths.rawStatusFile} (${rawStatus})`)
  console.log(`Script exit status: ${paths.statusFile} (${status})`)
}

function printFinalCheckSummary(paths: SandboxPaths, observerPlugin: string, marker: string, rawStatus: number, status: number): void {
  console.log(`Sandbox root: ${paths.sandboxRoot}`)
  console.log(`Worktree: ${paths.worktree}`)
  console.log(`Generated config: ${path.join(paths.opencodeConfigDir, "opencode.json")}`)
  console.log(`Generated observer plugin: ${observerPlugin}`)
  console.log(`Command: ${paths.commandFile}`)
  console.log(`Metadata: ${paths.metadataFile}`)
  console.log(`Logs: ${paths.logFile}`)
  console.log(`Raw events: ${paths.eventsFile}`)
  console.log(`Final-check marker: ${marker}`)
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
    if (subcommand === "orchestrator-final-check") return await runOrchestratorFinalCheck(args)
    if (subcommand === "single-agent") return await runSingleAgent(args)
    failUsage(`unknown subcommand: ${subcommand}`)
  } catch (error) {
    console.error(`error: ${(error as Error).message}`)
    return 1
  }
}

process.exitCode = await main()
