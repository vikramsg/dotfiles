import test from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"

const plugin = await import("./orchestration-state.js")
const INDEX_FILE = "index.json"
const STATE_FILE = "state.json"
const REQUEST_FILE = "request.md"

function toSessionRunId(sessionID) {
  return `session-${Buffer.from(sessionID, "utf8").toString("base64url")}`
}

function getTasksRoot(worktree) {
  return path.join(worktree, ".agents", "tasks")
}

function readRunState(tasksRoot, runId) {
  return JSON.parse(fs.readFileSync(path.join(tasksRoot, runId, STATE_FILE), "utf8"))
}

function makeWorkspace() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "orchestration-state-"))
}

async function loadHooks(worktree) {
  return plugin.OrchestrationStatePlugin({
    worktree,
    directory: worktree,
    client: {},
    project: {},
    serverUrl: new URL("http://127.0.0.1:4096"),
    $: {},
  })
}

test("command.execute.before resumes the same session and separates different sessions", async () => {
  const worktree = makeWorkspace()
  const hooks = await loadHooks(worktree)
  const firstOutput = { parts: [] }
  const session1 = "session-1"
  const session2 = "session-2"
  const runId1 = toSessionRunId(session1)
  const runId2 = toSessionRunId(session2)

  await hooks["command.execute.before"](
    {
      command: "orchestrate",
      sessionID: session1,
      arguments: "persist this request",
    },
    firstOutput,
  )

  const tasksRoot = getTasksRoot(worktree)
  const entries = fs.readdirSync(tasksRoot).filter((entry) => entry !== INDEX_FILE)
  assert.equal(entries.length, 1)

  assert.deepEqual(entries, [runId1])

  const runDir = path.join(tasksRoot, runId1)
  assert.equal(fs.existsSync(path.join(runDir, REQUEST_FILE)), true)
  assert.equal(fs.existsSync(path.join(runDir, STATE_FILE)), true)
  assert.equal(fs.readFileSync(path.join(runDir, REQUEST_FILE), "utf8"), "persist this request\n")
  assert.match(firstOutput.parts[0].text, /Mode: create\./)
  assert.match(firstOutput.parts[0].text, new RegExp(`Session ID: ${session1}`))
  assert.doesNotMatch(firstOutput.parts[0].text, /^Run ID:/m)

  const resumedOutput = { parts: [] }
  await hooks["command.execute.before"](
    {
      command: "orchestrate",
      sessionID: session1,
      arguments: "ignored on resume",
    },
    resumedOutput,
  )

  let state = readRunState(tasksRoot, runId1)
  assert.equal(state.runId, runId1)
  assert.equal(state.sessionID, session1)
  assert.equal(state.resumeCount, 1)
  assert.equal(fs.readFileSync(path.join(runDir, REQUEST_FILE), "utf8"), "persist this request\n")
  assert.match(resumedOutput.parts[0].text, /Mode: resume\./)

  await hooks["command.execute.before"](
    {
      command: "orchestrate",
      sessionID: session2,
      arguments: "new session should create its own run",
    },
    { parts: [] },
  )

  const runIds = fs.readdirSync(tasksRoot).filter((entry) => entry !== INDEX_FILE).sort()
  assert.deepEqual(runIds, [runId1, runId2])

  state = readRunState(tasksRoot, runId1)
  assert.equal(state.resumeCount, 1)
  assert.equal(fs.readFileSync(path.join(runDir, REQUEST_FILE), "utf8"), "persist this request\n")

  const secondState = readRunState(tasksRoot, runId2)
  assert.equal(secondState.sessionID, session2)
  assert.equal(secondState.resumeCount, 0)

  const index = JSON.parse(fs.readFileSync(path.join(tasksRoot, INDEX_FILE), "utf8"))
  assert.deepEqual(
    index.runs.map((entry) => entry.runId).sort(),
    [runId1, runId2],
  )
})

test("command.execute.before normalizes quoted requests", async () => {
  const worktree = makeWorkspace()
  const hooks = await loadHooks(worktree)

  await hooks["command.execute.before"](
    {
      command: "orchestrate",
      sessionID: "session-quoted",
      arguments: '"quoted request body"',
    },
    { parts: [] },
  )

  const tasksRoot = getTasksRoot(worktree)
  const runId = fs.readdirSync(tasksRoot).find((entry) => entry !== INDEX_FILE)
  assert.ok(runId)
  assert.equal(fs.readFileSync(path.join(tasksRoot, runId, REQUEST_FILE), "utf8"), "quoted request body\n")

  const state = readRunState(tasksRoot, runId)
  assert.equal(state.requestPreview, "quoted request body")
})

test("command.execute.before rejects wrong-cased sessionId", async () => {
  const worktree = makeWorkspace()
  const hooks = await loadHooks(worktree)

  await assert.rejects(
    () =>
      hooks["command.execute.before"](
        {
          command: "orchestrate",
          sessionId: "wrong-case",
          arguments: "request",
        },
        { parts: [] },
      ),
    /requires a non-empty sessionID/,
  )

  assert.equal(fs.existsSync(path.join(worktree, ".agents", "tasks")), false)
})

test("tool.execute.after persists planner, implementer, and reviewer task outputs", async () => {
  const worktree = makeWorkspace()
  const hooks = await loadHooks(worktree)
  const runId = toSessionRunId("session-2")

  await hooks["command.execute.before"](
    {
      command: "orchestrate",
      sessionID: "session-2",
      arguments: "run orchestration",
    },
    { parts: [] },
  )

  const tasksRoot = getTasksRoot(worktree)
  assert.ok(fs.existsSync(path.join(tasksRoot, runId, STATE_FILE)))

  await hooks["tool.execute.after"](
    {
      tool: "task",
      sessionID: "session-2",
      callID: "call-plan",
      args: { subagent_type: "planner" },
    },
    {
      title: "planner",
      output: "PLAN VERSION: 2\n\n## Executive Summary\n- planned\n",
      metadata: {},
    },
  )

  await hooks["tool.execute.after"](
    {
      tool: "task",
      sessionID: "session-2",
      callID: "call-implement",
      args: { subagent_type: "implementer" },
    },
    {
      title: "implementer",
      output: "## Implementation Summary\n- implemented\n",
      metadata: {},
    },
  )

  await hooks["tool.execute.after"](
    {
      tool: "task",
      sessionID: "session-2",
      callID: "call-review-fail",
      args: { subagent_type: "reviewer" },
    },
    {
      title: "reviewer",
      output: "---\nverdict: CHANGE_REQUIRED\n---\n",
      metadata: {},
    },
  )

  let state = readRunState(tasksRoot, runId)
  assert.equal(fs.existsSync(path.join(tasksRoot, runId, "plan.md")), true)
  assert.equal(fs.existsSync(path.join(tasksRoot, runId, "verification.md")), true)
  assert.equal(fs.existsSync(path.join(tasksRoot, runId, "review.md")), true)
  assert.equal(state.phase, "reviewed")
  assert.equal(state.status, "running")
  assert.equal(state.latest.reviewer.verdict, "CHANGE_REQUIRED")

  await hooks["tool.execute.after"](
    {
      tool: "task",
      sessionID: "session-2",
      callID: "call-review-pass",
      args: { subagent_type: "reviewer" },
    },
    {
      title: "reviewer",
      output: "---\nverdict: APPROVED\n---\n",
      metadata: {},
    },
  )

  state = readRunState(tasksRoot, runId)
  assert.equal(state.phase, "complete")
  assert.equal(state.status, "completed")

  const index = JSON.parse(fs.readFileSync(path.join(tasksRoot, INDEX_FILE), "utf8"))
  assert.equal(index.runs.some((entry) => entry.runId === runId), true)

  await hooks["command.execute.before"](
    {
      command: "orchestrate",
      sessionID: "session-2",
      arguments: "new request after completion",
    },
    { parts: [] },
  )

  const runIds = fs.readdirSync(tasksRoot).filter((entry) => entry !== INDEX_FILE)
  assert.deepEqual(runIds, [runId])

  state = readRunState(tasksRoot, runId)
  assert.equal(state.phase, "complete")
  assert.equal(state.status, "completed")
  assert.equal(state.resumeCount, 1)
})

test("tool.execute.after attaches artifacts only to the matching session run", async () => {
  const worktree = makeWorkspace()
  const hooks = await loadHooks(worktree)
  const session1 = "session-initial"
  const session2 = "session-resumed"
  const runId1 = toSessionRunId(session1)
  const runId2 = toSessionRunId(session2)

  await hooks["command.execute.before"](
    {
      command: "orchestrate",
      sessionID: session1,
      arguments: "persist across cli restarts",
    },
    { parts: [] },
  )

  await hooks["command.execute.before"](
    {
      command: "orchestrate",
      sessionID: session2,
      arguments: "new invocation should create a new run",
    },
    { parts: [] },
  )

  const tasksRoot = getTasksRoot(worktree)
  assert.deepEqual(
    fs.readdirSync(tasksRoot).filter((entry) => entry !== INDEX_FILE).sort(),
    [runId1, runId2],
  )

  await hooks["tool.execute.after"](
    {
      tool: "task",
      sessionID: session2,
      callID: "call-plan-resumed",
      args: { subagent_type: "planner" },
    },
    {
      title: "planner",
      output: "PLAN VERSION: 2\n\n## Executive Summary\n- resumed\n",
      metadata: {},
    },
  )

  assert.equal(fs.existsSync(path.join(tasksRoot, runId1, "plan.md")), false)
  assert.equal(fs.readFileSync(path.join(tasksRoot, runId2, "plan.md"), "utf8"), "PLAN VERSION: 2\n\n## Executive Summary\n- resumed\n")

  const state1 = readRunState(tasksRoot, runId1)
  assert.equal(state1.resumeCount, 0)
  assert.equal(state1.latest.planner, null)

  const state2 = readRunState(tasksRoot, runId2)
  assert.equal(state2.resumeCount, 0)
  assert.equal(state2.latest.planner.callID, "call-plan-resumed")
  assert.equal(state2.latest.planner.file, "plan.md")

  const index = JSON.parse(fs.readFileSync(path.join(tasksRoot, INDEX_FILE), "utf8"))
  assert.equal(index.runs.length, 2)
  assert.deepEqual(
    index.runs.map((entry) => ({ runId: entry.runId, phase: entry.phase, status: entry.status })).sort((left, right) => left.runId.localeCompare(right.runId)),
    [
      { runId: runId1, phase: "requested", status: "running" },
      { runId: runId2, phase: "planned", status: "running" },
    ],
  )
})

test("command.execute.before derives deterministic filesystem-safe run ids from session ids", async () => {
  const worktree = makeWorkspace()
  const hooks = await loadHooks(worktree)
  const sessionID = "session / unsafe ?#% with spaces"
  const otherSessionID = "session / unsafe ?#% with spaces!"
  const runId = toSessionRunId(sessionID)
  const otherRunId = toSessionRunId(otherSessionID)

  await hooks["command.execute.before"](
    {
      command: "orchestrate",
      sessionID,
      arguments: "unsafe session id",
    },
    { parts: [] },
  )

  await hooks["command.execute.before"](
    {
      command: "orchestrate",
      sessionID,
      arguments: "same session should map identically",
    },
    { parts: [] },
  )

  await hooks["command.execute.before"](
    {
      command: "orchestrate",
      sessionID: otherSessionID,
      arguments: "different session should not alias",
    },
    { parts: [] },
  )

  const tasksRoot = getTasksRoot(worktree)
  const runIds = fs.readdirSync(tasksRoot).filter((entry) => entry !== INDEX_FILE).sort()

  assert.deepEqual(runIds, [otherRunId, runId].sort())
  assert.match(runId, /^session-[A-Za-z0-9_-]+$/)
  assert.equal(runId.includes("/"), false)
  assert.equal(runId.includes(" "), false)
  assert.notEqual(runId, otherRunId)

  const state = readRunState(tasksRoot, runId)
  assert.equal(state.sessionID, sessionID)
  assert.equal(state.resumeCount, 1)
})

test("reviewer verdict parsing only accepts the canonical contract", async () => {
  const worktree = makeWorkspace()
  const hooks = await loadHooks(worktree)

  await hooks["command.execute.before"](
    {
      command: "orchestrate",
      sessionID: "session-3",
      arguments: "canonical reviewer contract",
    },
    { parts: [] },
  )

  const tasksRoot = getTasksRoot(worktree)
  const runId = fs.readdirSync(tasksRoot).find((entry) => entry !== INDEX_FILE)
  assert.ok(runId)

  await hooks["tool.execute.after"](
    {
      tool: "task",
      sessionID: "session-3",
      callID: "review-pass-fallback",
      args: { subagent_type: "reviewer" },
    },
    {
      title: "reviewer",
      output: "---\nverdict: PASS\n---\n",
      metadata: {},
    },
  )

  let state = readRunState(tasksRoot, runId)
  assert.equal(state.phase, "reviewed")
  assert.equal(state.status, "running")
  assert.equal(state.latest.reviewer.verdict, null)

  await hooks["tool.execute.after"](
    {
      tool: "task",
      sessionID: "session-3",
      callID: "review-fail-fallback",
      args: { subagent_type: "reviewer" },
    },
    {
      title: "reviewer",
      output: "---\nverdict: FAIL\n---\n",
      metadata: {},
    },
  )

  state = readRunState(tasksRoot, runId)
  assert.equal(state.phase, "reviewed")
  assert.equal(state.status, "running")
  assert.equal(state.latest.reviewer.verdict, null)

  await hooks["tool.execute.after"](
    {
      tool: "task",
      sessionID: "session-3",
      callID: "review-change-required",
      args: { subagent_type: "reviewer" },
    },
    {
      title: "reviewer",
      output: "---\nverdict: CHANGE_REQUIRED\n---\n",
      metadata: {},
    },
  )

  state = readRunState(tasksRoot, runId)
  assert.equal(state.phase, "reviewed")
  assert.equal(state.status, "running")
  assert.equal(state.latest.reviewer.verdict, "CHANGE_REQUIRED")

  await hooks["tool.execute.after"](
    {
      tool: "task",
      sessionID: "session-3",
      callID: "review-approved",
      args: { subagent_type: "reviewer" },
    },
    {
      title: "reviewer",
      output: "---\nverdict: APPROVED\n---\n",
      metadata: {},
    },
  )

  state = readRunState(tasksRoot, runId)
  assert.equal(state.phase, "complete")
  assert.equal(state.status, "completed")
  assert.equal(state.latest.reviewer.verdict, "APPROVED")
})

test("plugin initialization requires an OpenCode directory or worktree context", async () => {
  await assert.rejects(
    () => plugin.OrchestrationStatePlugin({ client: {}, project: {}, serverUrl: new URL("http://127.0.0.1:4096"), $: {} }),
    /requires a directory or worktree context/,
  )
})
