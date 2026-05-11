import test from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"

const plugin = await import("./orchestration-state.js")
const INDEX_FILE = "index.json"
const STATE_FILE = "state.json"
const REQUEST_FILE = "request.md"

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

test("command.execute.before reopens the latest nonterminal run across session changes", async () => {
  const worktree = makeWorkspace()
  const hooks = await loadHooks(worktree)
  const firstOutput = { parts: [] }

  await hooks["command.execute.before"](
    {
      command: "orchestrate",
      sessionID: "session-1",
      arguments: "persist this request",
    },
    firstOutput,
  )

  const tasksRoot = getTasksRoot(worktree)
  const entries = fs.readdirSync(tasksRoot).filter((entry) => entry !== INDEX_FILE)
  assert.equal(entries.length, 1)

  const runId = entries[0]
  const runDir = path.join(tasksRoot, runId)
  assert.equal(fs.existsSync(path.join(runDir, REQUEST_FILE)), true)
  assert.equal(fs.existsSync(path.join(runDir, STATE_FILE)), true)
  assert.equal(fs.readFileSync(path.join(runDir, REQUEST_FILE), "utf8"), "persist this request\n")
  assert.match(firstOutput.parts[0].text, new RegExp(runId))

  const resumedOutput = { parts: [] }
  await hooks["command.execute.before"](
    {
      command: "orchestrate",
      sessionID: "session-2",
      arguments: "ignored on resume",
    },
    resumedOutput,
  )

  const state = readRunState(tasksRoot, runId)
  assert.equal(state.runId, runId)
  assert.equal(state.resumeCount, 1)
  assert.equal(fs.readFileSync(path.join(runDir, REQUEST_FILE), "utf8"), "persist this request\n")
  assert.match(resumedOutput.parts[0].text, /Mode: resume\./)
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

test("tool.execute.after persists planner, implementer, and reviewer task outputs", async () => {
  const worktree = makeWorkspace()
  const hooks = await loadHooks(worktree)

  await hooks["command.execute.before"](
    {
      command: "orchestrate",
      sessionID: "session-2",
      arguments: "run orchestration",
    },
    { parts: [] },
  )

  const tasksRoot = getTasksRoot(worktree)
  const runId = fs.readdirSync(tasksRoot).find((entry) => entry !== INDEX_FILE)
  assert.ok(runId)

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
  assert.equal(runIds.length, 2)
})

test("tool.execute.after attaches artifacts to the reopened run after resume", async () => {
  const worktree = makeWorkspace()
  const hooks = await loadHooks(worktree)

  await hooks["command.execute.before"](
    {
      command: "orchestrate",
      sessionID: "session-initial",
      arguments: "persist across cli restarts",
    },
    { parts: [] },
  )

  const tasksRoot = getTasksRoot(worktree)
  const runId = fs.readdirSync(tasksRoot).find((entry) => entry !== INDEX_FILE)
  assert.ok(runId)

  await hooks["command.execute.before"](
    {
      command: "orchestrate",
      sessionID: "session-resumed",
      arguments: "new invocation should resume",
    },
    { parts: [] },
  )

  await hooks["tool.execute.after"](
    {
      tool: "task",
      sessionID: "session-resumed",
      callID: "call-plan-resumed",
      args: { subagent_type: "planner" },
    },
    {
      title: "planner",
      output: "PLAN VERSION: 2\n\n## Executive Summary\n- resumed\n",
      metadata: {},
    },
  )

  const runIds = fs.readdirSync(tasksRoot).filter((entry) => entry !== INDEX_FILE)
  assert.deepEqual(runIds, [runId])
  assert.equal(fs.readFileSync(path.join(tasksRoot, runId, "plan.md"), "utf8"), "PLAN VERSION: 2\n\n## Executive Summary\n- resumed\n")

  const state = readRunState(tasksRoot, runId)
  assert.equal(state.resumeCount, 1)
  assert.equal(state.latest.planner.callID, "call-plan-resumed")
  assert.equal(state.latest.planner.file, "plan.md")

  const index = JSON.parse(fs.readFileSync(path.join(tasksRoot, INDEX_FILE), "utf8"))
  assert.equal(index.runs.length, 1)
  assert.equal(index.runs[0].runId, runId)
  assert.equal(index.runs[0].phase, "planned")
  assert.equal(index.runs[0].status, "running")
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
