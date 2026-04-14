/**
 * Resume means a later orchestrate call in the same OpenCode session reuses the
 * exact persisted session folder under `.agents/tasks/<session-key>`.
 * Attach means a task result writes artifacts and state updates only into the
 * persisted folder mapped to the current OpenCode session ID.
 *
 * BDD scenarios:
 * - Given no persisted folder for session S1, when orchestrate runs for S1,
 *   then `.agents/tasks/<session-key(S1)>` is created with `request.md`,
 *   `state.json`, and `index.json`, and the context says `Mode: create.`
 * - Given a persisted folder for session S1, when orchestrate runs again for
 *   S1, then the plugin resumes that same folder and preserves `request.md`.
 * - Given a persisted folder for session S1, when orchestrate runs for S2 in
 *   the same worktree, then `.agents/tasks/<session-key(S2)>` is created and
 *   the S1 folder is not mutated.
 * - Given persisted folders for S1 and S2, when planner, implementer, or
 *   reviewer task output arrives for S2, then artifacts and state updates are
 *   written only inside `.agents/tasks/<session-key(S2)>`.
 * - Given a session ID with spaces or path-like characters, when the plugin
 *   derives a folder name, then the mapping is deterministic, filesystem-safe,
 *   and distinct from other session IDs.
 * - Given a terminal persisted state for S1, when orchestrate runs again for
 *   S1, then the plugin still resumes `.agents/tasks/<session-key(S1)>`
 *   instead of creating another folder.
 */
import crypto from "node:crypto"
import fs from "node:fs"
import path from "node:path"

const RUNS_RELATIVE_DIR = path.join(".agents", "tasks")
const INDEX_FILE = "index.json"
const STATE_FILE = "state.json"
const REQUEST_FILE = "request.md"
const ARTIFACT_FILES = {
  planner: "plan.md",
  implementer: "verification.md",
  reviewer: "review.md",
}

const REVIEWER_VERDICTS = new Set(["APPROVED", "CHANGE_REQUIRED"])

function nowISO() {
  return new Date().toISOString()
}

function ensureDirectory(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true })
}

function toComparableTimestamp(value) {
  return typeof value === "string" && value ? value : ""
}

function normalizeText(value) {
  if (typeof value === "string") {
    return value
  }
  if (value === undefined || value === null) {
    return ""
  }
  return JSON.stringify(value, null, 2)
}

function appendTrailingNewline(value) {
  return value.endsWith("\n") ? value : `${value}\n`
}

function writeTextFile(filePath, text) {
  ensureDirectory(path.dirname(filePath))
  const tempPath = `${filePath}.${process.pid}.${Date.now()}.${crypto.randomBytes(4).toString("hex")}.tmp`
  fs.writeFileSync(tempPath, text, "utf8")
  fs.renameSync(tempPath, filePath)
}

function writeJsonFile(filePath, value) {
  writeTextFile(filePath, `${JSON.stringify(value, null, 2)}\n`)
}

function readJsonFile(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"))
}

function getTasksRoot(worktree) {
  return path.join(worktree, RUNS_RELATIVE_DIR)
}

function unwrapQuotedString(text) {
  const trimmed = text.trim()
  if (!trimmed) {
    return ""
  }

  if (trimmed.startsWith('"') && trimmed.endsWith('"')) {
    try {
      const parsed = JSON.parse(trimmed)
      if (typeof parsed === "string") {
        return parsed.trim()
      }
    } catch {
      return trimmed.slice(1, -1).trim()
    }
  }

  if (trimmed.startsWith("'") && trimmed.endsWith("'")) {
    return trimmed.slice(1, -1).trim()
  }

  return trimmed
}

function normalizeRequestText(value) {
  if (typeof value === "string") {
    return unwrapQuotedString(value)
  }

  return unwrapQuotedString(normalizeText(value))
}

function normalizeDirectory(value) {
  return typeof value === "string" && value.trim() ? value : null
}

function requireSessionID(sessionID) {
  if (typeof sessionID !== "string" || !sessionID.trim()) {
    throw new Error("OrchestrationStatePlugin requires a non-empty sessionID")
  }

  return sessionID
}

function resolveSessionID(input) {
  return requireSessionID(input?.sessionID)
}

function toSessionRunId(sessionID) {
  return `session-${Buffer.from(requireSessionID(sessionID), "utf8").toString("base64url")}`
}

function resolveWorktreeDirectory(context) {
  const resolved = normalizeDirectory(context?.directory) || normalizeDirectory(context?.worktree)
  if (!resolved) {
    throw new Error("OrchestrationStatePlugin requires a directory or worktree context")
  }
  return resolved
}

function getRunDirectory(rootDir, runId) {
  return path.join(rootDir, runId)
}

function getRunFile(rootDir, runId, fileName) {
  return path.join(getRunDirectory(rootDir, runId), fileName)
}

function listRunIds(rootDir) {
  if (!fs.existsSync(rootDir)) {
    return []
  }

  return fs
    .readdirSync(rootDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort()
}

function readRunState(rootDir, runId) {
  const statePath = getRunFile(rootDir, runId, STATE_FILE)
  if (!fs.existsSync(statePath)) {
    return null
  }

  try {
    const state = readJsonFile(statePath)
    if (state && state.runId === runId) {
      return state
    }
  } catch {
    return null
  }

  return null
}

function collectRunStates(rootDir) {
  return listRunIds(rootDir)
    .map((runId) => readRunState(rootDir, runId))
    .filter(Boolean)
    .sort((left, right) => {
      const leftTimestamp = toComparableTimestamp(left.updatedAt || left.createdAt)
      const rightTimestamp = toComparableTimestamp(right.updatedAt || right.createdAt)
      return leftTimestamp.localeCompare(rightTimestamp)
    })
}

function buildIndex(rootDir) {
  return {
    updatedAt: nowISO(),
    runs: collectRunStates(rootDir).map((state) => ({
      runId: state.runId,
      sessionID: state.sessionID,
      worktree: state.worktree,
      createdAt: state.createdAt,
      updatedAt: state.updatedAt,
      phase: state.phase,
      status: state.status,
      reviewerVerdict: state.latest?.reviewer?.verdict || null,
    })),
  }
}

function rebuildIndex(rootDir) {
  ensureDirectory(rootDir)
  writeJsonFile(path.join(rootDir, INDEX_FILE), buildIndex(rootDir))
}

function previewText(text, limit = 240) {
  const normalized = normalizeText(text).replace(/\s+/g, " ").trim()
  if (!normalized) {
    return ""
  }
  return normalized.length <= limit ? normalized : `${normalized.slice(0, limit)}…`
}

function createInitialState({ runId, sessionID, worktree, requestText }) {
  const timestamp = nowISO()
  return {
    schemaVersion: 1,
    runId,
    sessionID,
    worktree,
    createdAt: timestamp,
    updatedAt: timestamp,
    phase: "requested",
    status: "running",
    resumeCount: 0,
    requestPreview: previewText(requestText),
    artifacts: {
      request: REQUEST_FILE,
      plan: ARTIFACT_FILES.planner,
      review: ARTIFACT_FILES.reviewer,
      verification: ARTIFACT_FILES.implementer,
      state: STATE_FILE,
    },
    latest: {
      planner: null,
      implementer: null,
      reviewer: null,
    },
    history: [
      {
        at: timestamp,
        role: "request",
        file: REQUEST_FILE,
      },
    ],
  }
}

function commitRunMutation(rootDir, runId, mutate) {
  ensureDirectory(rootDir)
  ensureDirectory(getRunDirectory(rootDir, runId))

  const currentState = readRunState(rootDir, runId)
  const mutation = mutate(currentState)
  if (!mutation || !mutation.state) {
    throw new Error(`Mutation for run ${runId} did not produce state`)
  }

  const files = mutation.files || {}
  for (const [fileName, content] of Object.entries(files)) {
    writeTextFile(getRunFile(rootDir, runId, fileName), appendTrailingNewline(normalizeText(content)))
  }

  writeJsonFile(getRunFile(rootDir, runId, STATE_FILE), mutation.state)
  rebuildIndex(rootDir)
  return mutation.state
}

function createTextPart(text) {
  return {
    type: "text",
    text,
  }
}

function ensureParts(output) {
  if (!Array.isArray(output.parts)) {
    output.parts = []
  }
  return output.parts
}

function buildRunContext(state, mode) {
  const summary = [
    "Persistent orchestration state is enabled for this run.",
    `Mode: ${mode}.`,
    `Session ID: ${state.sessionID}`,
    `Session folder: .agents/tasks/${state.runId}`,
    `Authoritative state: .agents/tasks/${state.runId}/state.json`,
    `Request: .agents/tasks/${state.runId}/request.md`,
    `Plan: .agents/tasks/${state.runId}/plan.md`,
    `Review: .agents/tasks/${state.runId}/review.md`,
    `Verification: .agents/tasks/${state.runId}/verification.md`,
    `Current phase: ${state.phase}`,
    `Current status: ${state.status}`,
  ]

  const reviewerVerdict = state.latest?.reviewer?.verdict
  if (reviewerVerdict) {
    summary.push(`Latest reviewer verdict: ${reviewerVerdict}`)
  }

  if (state.requestPreview) {
    summary.push(`Request summary: ${state.requestPreview}`)
  }

  summary.push("Use the persisted run artifacts above as the source of continuity for this orchestration run.")
  return summary.join("\n")
}

function classifyTaskRole(args) {
  const rawRole = args?.subagent_type ?? args?.subagentType ?? args?.agent ?? null
  if (typeof rawRole !== "string") {
    return null
  }

  const normalized = rawRole.trim().toLowerCase()
  if (normalized === "planner" || normalized === "implementer" || normalized === "reviewer") {
    return normalized
  }
  return null
}

function parseReviewerVerdict(markdown) {
  const match = normalizeText(markdown).match(/^\s*verdict:\s*([A-Z_]+)\s*$/im)
  const verdict = match ? match[1].toUpperCase() : null
  return REVIEWER_VERDICTS.has(verdict) ? verdict : null
}

function getPhaseForRole(role, verdict) {
  if (role === "planner") {
    return "planned"
  }
  if (role === "implementer") {
    return "implemented"
  }
  if (role === "reviewer") {
    if (verdict === "APPROVED") {
      return "complete"
    }
    return "reviewed"
  }
  return "running"
}

function getStatusForRole(role, verdict) {
  if (role === "reviewer" && verdict === "APPROVED") {
    return "completed"
  }
  return "running"
}

function updateLatestRoleState(state, role, payload) {
  return {
    ...(state.latest || {}),
    [role]: payload,
  }
}

function updateHistory(state, entry) {
  const history = Array.isArray(state.history) ? state.history.slice() : []
  history.push(entry)
  return history.slice(-100)
}

function persistTaskResult(worktree, input, output) {
  const role = classifyTaskRole(input.args)
  if (!role) {
    return null
  }

  const rootDir = getTasksRoot(worktree)
  const runId = toSessionRunId(resolveSessionID(input))
  const activeRun = readRunState(rootDir, runId)
  if (!activeRun) {
    return null
  }

  const timestamp = nowISO()
  const artifactFile = ARTIFACT_FILES[role]
  const outputText = normalizeText(output.output)
  const verdict = role === "reviewer" ? parseReviewerVerdict(outputText) : null

  return commitRunMutation(rootDir, runId, (state) => ({
    files: {
      [artifactFile]: outputText,
    },
    state: {
      ...state,
      updatedAt: timestamp,
      phase: getPhaseForRole(role, verdict),
      status: getStatusForRole(role, verdict),
      latest: updateLatestRoleState(state, role, {
        at: timestamp,
        callID: input.callID,
        title: output.title || "",
        file: artifactFile,
        verdict,
      }),
      history: updateHistory(state, {
        at: timestamp,
        role,
        callID: input.callID,
        file: artifactFile,
        verdict,
      }),
    },
  }))
}

export async function OrchestrationStatePlugin(context) {
  const worktree = resolveWorktreeDirectory(context)

  return {
    "command.execute.before": async (input, output) => {
      if (input.command !== "orchestrate") {
        return
      }

      const rootDir = getTasksRoot(worktree)
      const sessionID = resolveSessionID(input)
      const runId = toSessionRunId(sessionID)
      const requestText = normalizeRequestText(input.arguments)
      const resumableRun = readRunState(rootDir, runId)

      let state
      let mode
      if (resumableRun) {
        mode = "resume"
        state = commitRunMutation(rootDir, runId, (currentState) => {
          const timestamp = nowISO()
          return {
            state: {
              ...currentState,
              updatedAt: timestamp,
              resumeCount: (currentState.resumeCount || 0) + 1,
              lastResumedAt: timestamp,
            },
          }
        })
      } else {
        mode = "create"
        state = commitRunMutation(rootDir, runId, () => ({
          files: {
            [REQUEST_FILE]: requestText,
          },
          state: createInitialState({
            runId,
            sessionID,
            worktree,
            requestText,
          }),
        }))
      }

      ensureParts(output).push(createTextPart(buildRunContext(state, mode)))
    },

    "tool.execute.after": async (input, output) => {
      if (input.tool !== "task") {
        return
      }

      persistTaskResult(worktree, input, output)
    },
  }
}

export default OrchestrationStatePlugin
