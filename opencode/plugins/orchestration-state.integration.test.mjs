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
const configFile = path.join(repoRoot, "opencode", "opencode.json")

function makeWorkspace() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "orchestration-state-integration-"))
}

function runOrchestrate(worktree, request) {
  return spawnSync("opencode", ["run", "--command", "orchestrate", "--format", "json", request], {
    cwd: worktree,
    env: {
      ...process.env,
      OPENCODE_CONFIG: configFile,
    },
    stdio: "pipe",
    encoding: "utf8",
    timeout: 20000,
  })
}

function assertRunSucceeded(result) {
  if (result.error && result.error.code !== "ETIMEDOUT") {
    throw result.error
  }

  if (result.status !== 0 && result.error?.code !== "ETIMEDOUT") {
    throw new Error(result.stderr || result.stdout || `opencode exited with status ${result.status}`)
  }
}

test(
  "real OpenCode run creates persistent-state artifacts via configured plugin",
  { timeout: 120000 },
  async () => {
    const worktree = makeWorkspace()
    const request = "Persistent-state smoke test only. Do not edit files; just acknowledge the request."

    const result = runOrchestrate(worktree, request)
    assertRunSucceeded(result)

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
     assert.equal(fs.readFileSync(requestFile, "utf8"), `${request}\n`)

     const state = JSON.parse(fs.readFileSync(stateFile, "utf8"))
     assert.equal(state.runId, runId)
     assert.equal(state.worktree, worktree)
     assert.equal(state.status, "running")
     assert.equal(state.requestPreview, request)
     assert.equal(state.artifacts.request, "request.md")
     assert.equal(state.artifacts.state, "state.json")

     const index = JSON.parse(fs.readFileSync(indexFile, "utf8"))
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
  "real OpenCode run resumes the same nonterminal persisted run across CLI invocations",
  { timeout: 120000 },
  async () => {
    const worktree = makeWorkspace()

    assertRunSucceeded(runOrchestrate(worktree, "persistent state smoke 1"))
    assertRunSucceeded(runOrchestrate(worktree, "persistent state smoke 2"))

    const tasksRoot = path.join(worktree, ".agents", "tasks")
    const runIds = fs.readdirSync(tasksRoot).filter((entry) => entry !== "index.json")

    assert.equal(runIds.length, 1)

    const runId = runIds[0]
    const state = JSON.parse(fs.readFileSync(path.join(tasksRoot, runId, "state.json"), "utf8"))

    assert.equal(state.runId, runId)
    assert.equal(state.resumeCount, 1)
  },
)
