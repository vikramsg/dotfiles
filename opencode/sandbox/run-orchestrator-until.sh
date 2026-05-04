#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: opencode/sandbox/run-orchestrator-until.sh <subagent> <prompt...>

Runs the real OpenCode orchestrator command in an isolated sandbox config and
loads a generated runtime plugin that stops when the requested subagent is
reached. The sandbox is intentionally left in place with logs, raw JSON events,
command metadata, stop marker, and persistent orchestration state.

Environment:
  OPENCODE_SANDBOX_ROOT        Reuse/create this sandbox root instead of mktemp.
  OPENCODE_SANDBOX_STOP_PHASE  "after" (default) or "before".
  OPENCODE_SANDBOX_MODEL       Override the generated sandbox model.
EOF
}

if [[ $# -lt 2 ]]; then
  usage >&2
  exit 64
fi

STOP_AT="$1"
shift
PROMPT="$*"
STOP_PHASE="${OPENCODE_SANDBOX_STOP_PHASE:-after}"

if [[ "$STOP_PHASE" != "after" && "$STOP_PHASE" != "before" ]]; then
  printf 'error: OPENCODE_SANDBOX_STOP_PHASE must be "after" or "before"\n' >&2
  exit 64
fi

if ! command -v opencode >/dev/null 2>&1; then
  printf 'error: opencode CLI was not found on PATH\n' >&2
  exit 127
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE_CONFIG="$REPO_ROOT/opencode/opencode.json"
SANDBOX_ROOT="${OPENCODE_SANDBOX_ROOT:-"$(mktemp -d -t opencode-sandbox-XXXXXXXX)"}"
CONFIG_HOME="$SANDBOX_ROOT/config"
DATA_HOME="$SANDBOX_ROOT/data"
CACHE_HOME="$SANDBOX_ROOT/cache"
STATE_HOME="$SANDBOX_ROOT/state"
OPENCODE_CONFIG_DIR="$CONFIG_HOME/opencode"
PLUGIN_DIR="$OPENCODE_CONFIG_DIR/plugins"
WORKTREE="$SANDBOX_ROOT/worktree"
OUTPUT_DIR="$SANDBOX_ROOT/output"
STOP_PLUGIN="$PLUGIN_DIR/stop-at-subagent.js"
STOP_MARKER="$OUTPUT_DIR/stop-marker.json"

mkdir -p "$OPENCODE_CONFIG_DIR" "$PLUGIN_DIR" "$WORKTREE" "$OUTPUT_DIR" "$DATA_HOME" "$CACHE_HOME" "$STATE_HOME"

USER_OPENCODE_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/opencode"
USER_OPENCODE_DB="$USER_OPENCODE_DATA_HOME/opencode.db"
SANDBOX_OPENCODE_DATA_HOME="$DATA_HOME/opencode"
mkdir -p "$SANDBOX_OPENCODE_DATA_HOME"
for auth_file in auth.json mcp-auth.json; do
  if [[ -f "$USER_OPENCODE_DATA_HOME/$auth_file" && ! -e "$SANDBOX_OPENCODE_DATA_HOME/$auth_file" ]]; then
    cp "$USER_OPENCODE_DATA_HOME/$auth_file" "$SANDBOX_OPENCODE_DATA_HOME/$auth_file"
  fi
done

link_repo_dir() {
  local source="$1"
  local target="$2"

  if [[ -e "$target" || -L "$target" ]]; then
    if [[ -L "$target" && "$(readlink "$target")" == "$source" ]]; then
      return 0
    fi
    printf 'error: sandbox path already exists and is not the expected symlink: %s\n' "$target" >&2
    exit 1
  fi

  ln -s "$source" "$target"
}

link_repo_dir "$REPO_ROOT/opencode/agents" "$OPENCODE_CONFIG_DIR/agents"
link_repo_dir "$REPO_ROOT/opencode/commands" "$OPENCODE_CONFIG_DIR/commands"

cat > "$STOP_PLUGIN" <<'PLUGIN'
import fs from "node:fs"
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
  return text.length <= limit ? text : `${text.slice(0, limit)}…`
}

function writeStopMarker(payload) {
  const markerPath = process.env.OPENCODE_SANDBOX_STOP_MARKER
  if (!markerPath) return
  fs.mkdirSync(path.dirname(markerPath), { recursive: true })
  fs.writeFileSync(markerPath, `${JSON.stringify(payload, null, 2)}\n`)
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

  throw new Error(`OPENCODE_SANDBOX_STOP ${phase} ${subagent}`)
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
    "tool.execute.before": async (input, output) => {
      stopIfMatched("before", input, null, output)
    },
    "tool.execute.after": async (input, output) => {
      stopIfMatched("after", input, output)
    },
  }
}
PLUGIN

node - "$REPO_ROOT" "$SOURCE_CONFIG" "$OPENCODE_CONFIG_DIR/opencode.json" "$STOP_PLUGIN" <<'NODE'
const fs = require("node:fs")
const path = require("node:path")

const [repoRoot, sourceConfig, targetConfig, stopPlugin] = process.argv.slice(2)
const config = JSON.parse(fs.readFileSync(sourceConfig, "utf8"))

function configuredModelExists(value) {
  const [providerID, modelID] = String(value || "").split("/")
  if (!providerID || !modelID) return true
  return Boolean(config.provider?.[providerID]?.models?.[modelID])
}

function normalizeModel(value) {
  if (configuredModelExists(value)) return value
  const [providerID, modelID] = String(value || "").split("/")
  if (!providerID || !modelID) return value
  const dotted = modelID.replace(/-(\d+)$/, ".$1")
  const candidate = `${providerID}/${dotted}`
  return configuredModelExists(candidate) ? candidate : value
}

config.instructions = [path.join(repoRoot, "opencode", "rules.md")]
config.model = process.env.OPENCODE_SANDBOX_MODEL || normalizeModel(config.model)
config.plugin = (config.plugin || []).map((plugin) => {
  if (plugin === "./plugins/orchestration-state.js") {
    return path.join(repoRoot, "opencode", "plugins", "orchestration-state.js")
  }
  return plugin
})
config.plugin.push(stopPlugin)

fs.writeFileSync(targetConfig, `${JSON.stringify(config, null, 2)}\n`)
NODE

COMMAND_FILE="$OUTPUT_DIR/command.txt"
EVENTS_FILE="$OUTPUT_DIR/events.jsonl"
LOG_FILE="$OUTPUT_DIR/opencode.log"
STATUS_FILE="$OUTPUT_DIR/exit-status.txt"
RAW_STATUS_FILE="$OUTPUT_DIR/opencode-exit-status.txt"
METADATA_FILE="$OUTPUT_DIR/metadata.json"

rm -f -- \
  "$STOP_MARKER" \
  "$STATUS_FILE" \
  "$RAW_STATUS_FILE"

printf 'XDG_CONFIG_HOME=%q XDG_DATA_HOME=%q XDG_CACHE_HOME=%q XDG_STATE_HOME=%q OPENCODE_SANDBOX_STOP_AT=%q OPENCODE_SANDBOX_STOP_PHASE=%q OPENCODE_SANDBOX_STOP_MARKER=%q opencode run --dir %q --command orchestrate --format json --print-logs --log-level DEBUG %q\n' \
  "$CONFIG_HOME" "$DATA_HOME" "$CACHE_HOME" "$STATE_HOME" "$STOP_AT" "$STOP_PHASE" "$STOP_MARKER" "$WORKTREE" "$PROMPT" > "$COMMAND_FILE"

node - "$SANDBOX_ROOT" "$CONFIG_HOME" "$DATA_HOME" "$CACHE_HOME" "$STATE_HOME" "$WORKTREE" "$OUTPUT_DIR" "$STOP_AT" "$STOP_PHASE" "$PROMPT" "$STOP_PLUGIN" "$STOP_MARKER" > "$METADATA_FILE" <<'NODE'
const [sandboxRoot, configHome, dataHome, cacheHome, stateHome, worktree, outputDir, stopAt, stopPhase, prompt, stopPlugin, stopMarker] = process.argv.slice(2)
process.stdout.write(JSON.stringify({
  sandboxRoot,
  configHome,
  dataHome,
  cacheHome,
  stateHome,
  worktree,
  outputDir,
  stopAt,
  stopPhase,
  prompt,
  stopPlugin,
  stopMarker,
  stateRoot: `${worktree}/.agents/tasks`,
  generatedAt: new Date().toISOString(),
}, null, 2) + "\n")
NODE

set +e
(
  XDG_CONFIG_HOME="$CONFIG_HOME" \
  XDG_DATA_HOME="$DATA_HOME" \
  XDG_CACHE_HOME="$CACHE_HOME" \
  XDG_STATE_HOME="$STATE_HOME" \
  OPENCODE_SANDBOX_STOP_AT="$STOP_AT" \
  OPENCODE_SANDBOX_STOP_PHASE="$STOP_PHASE" \
  OPENCODE_SANDBOX_STOP_MARKER="$STOP_MARKER" \
    opencode run \
      --dir "$WORKTREE" \
      --command orchestrate \
      --format json \
      --print-logs \
      --log-level DEBUG \
      "$PROMPT"
) > "$EVENTS_FILE" 2> "$LOG_FILE" &
OPENCODE_PID=$!

while kill -0 "$OPENCODE_PID" >/dev/null 2>&1; do
  if [[ -s "$STOP_MARKER" ]]; then
    sleep 1
    kill -TERM "$OPENCODE_PID" >/dev/null 2>&1 || true
    break
  fi
  sleep 0.2
done

wait "$OPENCODE_PID"
STATUS=$?
set -e

RAW_STATUS="$STATUS"

VALIDATION_STATUS="$(node - "$LOG_FILE" "$EVENTS_FILE" "$STOP_MARKER" "$STOP_AT" "$STOP_PHASE" "$USER_OPENCODE_DB" <<'NODE'
const fs = require("node:fs")
const [logPath, eventsPath, markerPath, stopAt, stopPhase, realDb] = process.argv.slice(2)
const errors = []
const log = fs.existsSync(logPath) ? fs.readFileSync(logPath, "utf8") : ""
if (log.includes("Falling back to default agent")) errors.push("log contains default-agent fallback")
if (log.includes(realDb)) errors.push(`log contains user OpenCode database path: ${realDb}`)

function containsValue(value, expected) {
  if (!expected) return false
  if (value === expected) return true
  if (Array.isArray(value)) return value.some((item) => containsValue(item, expected))
  if (value && typeof value === "object") return Object.values(value).some((item) => containsValue(item, expected))
  return false
}

let events = []
try {
  const text = fs.existsSync(eventsPath) ? fs.readFileSync(eventsPath, "utf8") : ""
  for (const [index, line] of text.split(/\n/).entries()) {
    if (!line.trim()) continue
    try {
      events.push(JSON.parse(line))
    } catch (error) {
      errors.push(`events.jsonl line ${index + 1} is not valid JSON: ${error.message}`)
    }
  }
} catch (error) {
  errors.push(`cannot read events.jsonl: ${error.message}`)
}
if (events.length < 2 || !events.some((event) => event?.type !== "step_start")) {
  errors.push("events.jsonl does not contain meaningful OpenCode events")
}

if (!fs.existsSync(markerPath)) {
  errors.push("stop marker was not written")
} else {
  try {
    const marker = JSON.parse(fs.readFileSync(markerPath, "utf8"))
    if (marker.phase !== stopPhase) errors.push(`stop marker phase ${marker.phase || "<missing>"}, expected ${stopPhase}`)
    if (marker.subagent !== stopAt) errors.push(`stop marker subagent ${marker.subagent || "<missing>"}, expected ${stopAt}`)
    if (marker.observedSubagent !== stopAt) errors.push(`stop marker observed ${marker.observedSubagent || "<missing>"}, expected ${stopAt}`)
    if (!marker.callID) {
      errors.push("stop marker callID is missing")
    } else if (!events.some((event) => containsValue(event, marker.callID))) {
      errors.push(`stop marker callID ${marker.callID} was not found in current events.jsonl`)
    }
  } catch (error) {
    errors.push(`stop marker is not valid JSON: ${error.message}`)
  }
}

for (const error of errors) console.error(`validation error: ${error}`)
process.stdout.write(errors.length ? "invalid" : "ok")
NODE
)"

if [[ -s "$STOP_MARKER" && "$VALIDATION_STATUS" == "ok" ]]; then
  STATUS=0
else
  STATUS=1
fi

printf '%s\n' "$STATUS" > "$STATUS_FILE"
printf '%s\n' "$RAW_STATUS" > "$RAW_STATUS_FILE"

printf 'Sandbox root: %s\n' "$SANDBOX_ROOT"
printf 'Worktree: %s\n' "$WORKTREE"
printf 'Generated config: %s\n' "$OPENCODE_CONFIG_DIR/opencode.json"
printf 'Generated stop plugin: %s\n' "$STOP_PLUGIN"
printf 'Command: %s\n' "$COMMAND_FILE"
printf 'Metadata: %s\n' "$METADATA_FILE"
printf 'Logs: %s\n' "$LOG_FILE"
printf 'Raw events: %s\n' "$EVENTS_FILE"
printf 'Stop marker: %s\n' "$STOP_MARKER"
printf 'Persistent state root: %s\n' "$WORKTREE/.agents/tasks"
printf 'OpenCode CLI exit status: %s (%s)\n' "$RAW_STATUS_FILE" "$RAW_STATUS"
printf 'Script exit status: %s (%s)\n' "$STATUS_FILE" "$STATUS"

exit "$STATUS"
