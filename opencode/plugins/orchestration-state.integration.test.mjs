import test from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"

const currentFile = fileURLToPath(import.meta.url)
const pluginsDir = path.dirname(currentFile)
const repoRoot = path.resolve(pluginsDir, "..", "..")
const opencodeDir = path.join(repoRoot, "opencode")
const INSTALLED_ENTRIES = ["opencode.json", "tui.json", "rules.md", "agents", "commands", "plugins"]

function makeWorkspace() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "orchestration-state-integration-"))
}

function makeHome() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "orchestration-state-home-"))
}

function installOpencodeConfig(tempHome, entries = INSTALLED_ENTRIES) {
  const configDir = path.join(tempHome, ".config", "opencode")
  fs.mkdirSync(configDir, { recursive: true })

  for (const entry of entries) {
    fs.symlinkSync(path.join(opencodeDir, entry), path.join(configDir, entry))
  }

  return configDir
}

function makeSpawnEnv(tempHome) {
  return {
    ...process.env,
    HOME: tempHome,
    XDG_CONFIG_HOME: path.join(tempHome, ".config"),
    XDG_STATE_HOME: path.join(tempHome, ".local", "state"),
    XDG_DATA_HOME: path.join(tempHome, ".local", "share"),
  }
}

function runOrchestrate(worktree, request, tempHome) {
  return spawnSync("opencode", ["run", "--print-logs", "--command", "orchestrate", "--format", "json", "--dir", worktree, request], {
    cwd: os.tmpdir(),
    env: makeSpawnEnv(tempHome),
    stdio: "pipe",
    encoding: "utf8",
    timeout: 60000,
  })
}

function runOrchestrateWithTimeout(worktree, request, tempHome, duration = "60s") {
  return spawnSync("timeout", [duration, "opencode", "run", "--print-logs", "--command", "orchestrate", "--format", "json", "--dir", worktree, request], {
    cwd: os.tmpdir(),
    env: makeSpawnEnv(tempHome),
    stdio: "pipe",
    encoding: "utf8",
    timeout: 120000,
  })
}

function assertRunSucceeded(result) {
  if (result.error) {
    throw result.error
  }

  if (result.status !== 0) {
    throw new Error(result.stderr || result.stdout || `opencode exited with status ${result.status}`)
  }
}

function assertRunCompletedOrTimedOut(result) {
  if (result.error) {
    throw result.error
  }

  if (result.status !== 0 && result.status !== 124) {
    throw new Error(result.stderr || result.stdout || `opencode exited with status ${result.status}`)
  }
}

function assertSinglePersistedRun(worktree, expectedRequest) {
  const tasksRoot = path.join(worktree, ".agents", "tasks")
  const runIds = fs.readdirSync(tasksRoot).filter((entry) => entry !== "index.json")

  assert.equal(runIds.length, 1)

  const runId = runIds[0]
  const runDir = path.join(tasksRoot, runId)
  const requestFile = path.join(runDir, "request.md")
  const stateFile = path.join(runDir, "state.json")
  const indexFile = path.join(tasksRoot, "index.json")

  assert.equal(fs.existsSync(requestFile), true)
  assert.equal(fs.existsSync(stateFile), true)
  assert.equal(fs.existsSync(indexFile), true)
  assert.equal(fs.readFileSync(requestFile, "utf8"), `${expectedRequest}\n`)

  return {
    tasksRoot,
    runId,
    state: JSON.parse(fs.readFileSync(stateFile, "utf8")),
    index: JSON.parse(fs.readFileSync(indexFile, "utf8")),
  }
}

test(
  "real OpenCode run does not persist orchestration state when the installed plugin path is missing",
  { timeout: 120000 },
  async () => {
    const tempHome = makeHome()
    installOpencodeConfig(tempHome, INSTALLED_ENTRIES.filter((entry) => entry !== "plugins"))
    const worktree = makeWorkspace()

    const result = runOrchestrate(worktree, "missing installed plugin smoke test", tempHome)
    assertRunSucceeded(result)

    assert.equal(fs.existsSync(path.join(worktree, ".agents", "tasks")), false)
    assert.equal(fs.existsSync(path.join(tempHome, ".config", "opencode", "plugins", "orchestration-state.js")), false)
  },
)

test(
  "real OpenCode run ignores external XDG config when the installed plugin path is missing",
  { timeout: 120000 },
  async () => {
    const previousXdgConfigHome = process.env.XDG_CONFIG_HOME
    const previousXdgStateHome = process.env.XDG_STATE_HOME
    const previousXdgDataHome = process.env.XDG_DATA_HOME
    const externalHome = makeHome()
    const tempHome = makeHome()
    const worktree = makeWorkspace()

    installOpencodeConfig(externalHome)
    installOpencodeConfig(tempHome, INSTALLED_ENTRIES.filter((entry) => entry !== "plugins"))

    process.env.XDG_CONFIG_HOME = path.join(externalHome, ".config")
    process.env.XDG_STATE_HOME = path.join(externalHome, ".local", "state")
    process.env.XDG_DATA_HOME = path.join(externalHome, ".local", "share")

    try {
      const result = runOrchestrate(worktree, "external xdg missing plugin smoke test", tempHome)
      assertRunSucceeded(result)
    } finally {
      if (previousXdgConfigHome === undefined) {
        delete process.env.XDG_CONFIG_HOME
      } else {
        process.env.XDG_CONFIG_HOME = previousXdgConfigHome
      }

      if (previousXdgStateHome === undefined) {
        delete process.env.XDG_STATE_HOME
      } else {
        process.env.XDG_STATE_HOME = previousXdgStateHome
      }

      if (previousXdgDataHome === undefined) {
        delete process.env.XDG_DATA_HOME
      } else {
        process.env.XDG_DATA_HOME = previousXdgDataHome
      }
    }

    assert.equal(fs.existsSync(path.join(worktree, ".agents", "tasks")), false)
    assert.equal(fs.existsSync(path.join(externalHome, ".config", "opencode", "plugins", "orchestration-state.js")), true)
    assert.equal(fs.existsSync(path.join(tempHome, ".config", "opencode", "plugins", "orchestration-state.js")), false)
  },
)

test(
  "real OpenCode run still persists orchestration state when installed rules.md is missing",
  { timeout: 120000 },
  async () => {
    const tempHome = makeHome()
    installOpencodeConfig(tempHome, INSTALLED_ENTRIES.filter((entry) => entry !== "rules.md"))
    const worktree = makeWorkspace()
    const request = "rules missing smoke test"

    const result = runOrchestrate(worktree, request, tempHome)
    assertRunSucceeded(result)

    const persisted = assertSinglePersistedRun(worktree, request)

    assert.equal(fs.existsSync(path.join(tempHome, ".config", "opencode", "rules.md")), false)
    assert.equal(persisted.state.runId, persisted.runId)
    assert.equal(persisted.state.worktree, worktree)
    assert.equal(persisted.index.runs.length, 1)
    assert.equal(persisted.index.runs[0].runId, persisted.runId)
  },
)

test(
  "real OpenCode run creates persistent-state artifacts via installed config discovery",
  { timeout: 120000 },
  async () => {
    const tempHome = makeHome()
    installOpencodeConfig(tempHome)
    const worktree = makeWorkspace()
    const request = "Persistent-state smoke test only. Do not edit files; just acknowledge the request."

    const result = runOrchestrate(worktree, request, tempHome)
    assertRunSucceeded(result)

    const { runId, state, index } = assertSinglePersistedRun(worktree, request)

    assert.equal(state.runId, runId)
    assert.equal(state.worktree, worktree)
    assert.equal(state.status, "running")
    assert.equal(state.requestPreview, request)
    assert.equal(state.artifacts.request, "request.md")
    assert.equal(state.artifacts.state, "state.json")

    assert.equal(Array.isArray(index.runs), true)
    assert.equal(index.runs.length, 1)
    assert.deepEqual(index.runs[0], {
      runId,
      sessionID: state.sessionID,
      worktree,
      createdAt: state.createdAt,
      updatedAt: state.updatedAt,
      phase: state.phase,
      status: state.status,
      reviewerVerdict: null,
    })
  },
)

test(
  "real OpenCode run accepts persisted artifact verification with exit status 0 or 124",
  { timeout: 120000 },
  async () => {
    const tempHome = makeHome()
    installOpencodeConfig(tempHome)
    const worktree = makeWorkspace()
    const request = "timeout-compatible persistence smoke test"

    const result = runOrchestrateWithTimeout(worktree, request, tempHome)
    assertRunCompletedOrTimedOut(result)

    const persisted = assertSinglePersistedRun(worktree, request)

    assert.equal([0, 124].includes(result.status), true)
    assert.equal(persisted.state.runId, persisted.runId)
    assert.equal(persisted.index.runs[0].runId, persisted.runId)
  },
)

test(
  "real OpenCode run resumes the same nonterminal persisted run across CLI invocations",
  { timeout: 120000 },
  async () => {
    const tempHome = makeHome()
    installOpencodeConfig(tempHome)
    const worktree = makeWorkspace()

    assertRunSucceeded(runOrchestrate(worktree, "persistent state smoke 1", tempHome))
    assertRunSucceeded(runOrchestrate(worktree, "persistent state smoke 2", tempHome))

    const tasksRoot = path.join(worktree, ".agents", "tasks")
    const runIds = fs.readdirSync(tasksRoot).filter((entry) => entry !== "index.json")

    assert.equal(runIds.length, 1)

    const runId = runIds[0]
    const state = JSON.parse(fs.readFileSync(path.join(tasksRoot, runId, "state.json"), "utf8"))

    assert.equal(state.runId, runId)
    assert.equal(state.resumeCount, 1)
  },
)
