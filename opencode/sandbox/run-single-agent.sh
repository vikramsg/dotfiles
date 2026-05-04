#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: opencode/sandbox/run-single-agent.sh <agent> <prompt...>

Runs a real OpenCode agent/subagent in an isolated sandbox config and leaves
logs, raw JSON events, command metadata, and exit status under the printed
sandbox output directory.

Environment:
  OPENCODE_SANDBOX_ROOT  Reuse/create this sandbox root instead of mktemp.
  OPENCODE_SANDBOX_MODEL Override the generated sandbox model.
EOF
}

if [[ $# -lt 2 ]]; then
  usage >&2
  exit 64
fi

AGENT_NAME="$1"
shift
PROMPT="$*"

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
SANDBOX_AGENTS_DIR="$OPENCODE_CONFIG_DIR/agents"
PLUGIN_DIR="$OPENCODE_CONFIG_DIR/plugins"
WORKTREE="$SANDBOX_ROOT/worktree"
OUTPUT_DIR="$SANDBOX_ROOT/output"
OBSERVER_PLUGIN="$PLUGIN_DIR/single-agent-observer.js"
SINGLE_AGENT_MARKER="$OUTPUT_DIR/single-agent-marker.json"

mkdir -p "$OPENCODE_CONFIG_DIR" "$SANDBOX_AGENTS_DIR" "$PLUGIN_DIR" "$WORKTREE" "$OUTPUT_DIR" "$DATA_HOME" "$CACHE_HOME" "$STATE_HOME"

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

for source_agent in "$REPO_ROOT"/opencode/agents/*.md; do
  link_repo_dir "$source_agent" "$SANDBOX_AGENTS_DIR/$(basename "$source_agent")"
done
link_repo_dir "$REPO_ROOT/opencode/commands" "$OPENCODE_CONFIG_DIR/commands"

AGENT_FILE="$SANDBOX_AGENTS_DIR/$AGENT_NAME.md"
if [[ ! -e "$AGENT_FILE" ]]; then
  printf 'error: agent file was not found in sandbox config: %s\n' "$AGENT_FILE" >&2
  exit 66
fi

AGENT_MODE="$(node - "$AGENT_FILE" <<'NODE'
const fs = require("node:fs")
const file = process.argv[2]
const text = fs.readFileSync(file, "utf8")
const match = text.match(/^---\n([\s\S]*?)\n---/)
const frontmatter = match ? match[1] : ""
const mode = frontmatter.match(/^mode:\s*([^\n#]+)/m)?.[1]?.trim() || "primary"
process.stdout.write(mode)
NODE
)"

RUN_AGENT="$AGENT_NAME"
RUN_PROMPT="$PROMPT"

if [[ "$AGENT_MODE" == "subagent" ]]; then
  RUN_AGENT="sandbox-single-agent-harness"
  cat > "$SANDBOX_AGENTS_DIR/sandbox-single-agent-harness.md" <<'HARNESS'
---
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
HARNESS
  RUN_PROMPT="Requested subagent: $AGENT_NAME

User prompt:
$PROMPT"
fi

cat > "$OBSERVER_PLUGIN" <<'PLUGIN'
import fs from "node:fs"
import path from "node:path"

function getSubagent(input, hookOutput = null) {
  return input?.args?.subagent_type || input?.args?.subagentType || input?.args?.agent ||
    hookOutput?.args?.subagent_type || hookOutput?.args?.subagentType || hookOutput?.args?.agent || ""
}

function writeMarker(payload) {
  const markerPath = process.env.OPENCODE_SANDBOX_SINGLE_AGENT_MARKER
  if (!markerPath) return
  fs.mkdirSync(path.dirname(markerPath), { recursive: true })
  fs.writeFileSync(markerPath, `${JSON.stringify(payload, null, 2)}\n`)
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
    "tool.execute.before": async (input, output) => {
      observe("before", input, null, output)
    },
    "tool.execute.after": async (input, output) => {
      observe("after", input, output)
    },
  }
}
PLUGIN

node - "$REPO_ROOT" "$SOURCE_CONFIG" "$OPENCODE_CONFIG_DIR/opencode.json" "$OBSERVER_PLUGIN" <<'NODE'
const fs = require("node:fs")
const path = require("node:path")

const [repoRoot, sourceConfig, targetConfig, observerPlugin] = process.argv.slice(2)
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
config.plugin.push(observerPlugin)

fs.writeFileSync(targetConfig, `${JSON.stringify(config, null, 2)}\n`)
NODE

COMMAND_FILE="$OUTPUT_DIR/command.txt"
EVENTS_FILE="$OUTPUT_DIR/events.jsonl"
LOG_FILE="$OUTPUT_DIR/opencode.log"
STATUS_FILE="$OUTPUT_DIR/exit-status.txt"
RAW_STATUS_FILE="$OUTPUT_DIR/opencode-exit-status.txt"
METADATA_FILE="$OUTPUT_DIR/metadata.json"

rm -f -- \
  "$SINGLE_AGENT_MARKER" \
  "$STATUS_FILE" \
  "$RAW_STATUS_FILE"

printf 'XDG_CONFIG_HOME=%q XDG_DATA_HOME=%q XDG_CACHE_HOME=%q XDG_STATE_HOME=%q OPENCODE_SANDBOX_SINGLE_AGENT=%q OPENCODE_SANDBOX_SINGLE_AGENT_MARKER=%q opencode run --dir %q --agent %q --format json --print-logs --log-level DEBUG %q\n' \
  "$CONFIG_HOME" "$DATA_HOME" "$CACHE_HOME" "$STATE_HOME" "$AGENT_NAME" "$SINGLE_AGENT_MARKER" "$WORKTREE" "$RUN_AGENT" "$RUN_PROMPT" > "$COMMAND_FILE"

node - "$SANDBOX_ROOT" "$CONFIG_HOME" "$DATA_HOME" "$CACHE_HOME" "$STATE_HOME" "$WORKTREE" "$OUTPUT_DIR" "$AGENT_NAME" "$AGENT_MODE" "$RUN_AGENT" "$PROMPT" "$OBSERVER_PLUGIN" "$SINGLE_AGENT_MARKER" > "$METADATA_FILE" <<'NODE'
const [sandboxRoot, configHome, dataHome, cacheHome, stateHome, worktree, outputDir, agent, agentMode, runAgent, prompt, observerPlugin, singleAgentMarker] = process.argv.slice(2)
process.stdout.write(JSON.stringify({
  sandboxRoot,
  configHome,
  dataHome,
  cacheHome,
  stateHome,
  worktree,
  outputDir,
  agent,
  agentMode,
  runAgent,
  prompt,
  observerPlugin,
  singleAgentMarker,
  generatedAt: new Date().toISOString(),
}, null, 2) + "\n")
NODE

set +e
XDG_CONFIG_HOME="$CONFIG_HOME" \
XDG_DATA_HOME="$DATA_HOME" \
XDG_CACHE_HOME="$CACHE_HOME" \
XDG_STATE_HOME="$STATE_HOME" \
OPENCODE_SANDBOX_SINGLE_AGENT="$AGENT_NAME" \
OPENCODE_SANDBOX_SINGLE_AGENT_MARKER="$SINGLE_AGENT_MARKER" \
  opencode run \
    --dir "$WORKTREE" \
    --agent "$RUN_AGENT" \
    --format json \
    --print-logs \
    --log-level DEBUG \
    "$RUN_PROMPT" \
    > "$EVENTS_FILE" \
    2> "$LOG_FILE"
STATUS=$?
set -e

RAW_STATUS="$STATUS"

if [[ "$STATUS" -eq 0 ]]; then
  EVENT_ERROR="$(node - "$EVENTS_FILE" <<'NODE'
const fs = require("node:fs")
const eventsPath = process.argv[2]
let hasError = false
for (const line of fs.readFileSync(eventsPath, "utf8").split(/\n+/)) {
  if (!line.trim()) continue
  try {
    if (JSON.parse(line).type === "error") hasError = true
  } catch {}
}
process.stdout.write(hasError ? "error" : "ok")
NODE
)"
  if [[ "$EVENT_ERROR" == "error" ]]; then
    STATUS=1
  fi
fi

VALIDATION_STATUS="$(node - "$LOG_FILE" "$EVENTS_FILE" "$SINGLE_AGENT_MARKER" "$AGENT_NAME" "$AGENT_MODE" "$USER_OPENCODE_DB" <<'NODE'
const fs = require("node:fs")
const [logPath, eventsPath, markerPath, agent, agentMode, realDb] = process.argv.slice(2)
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

if (agentMode === "subagent") {
  if (!fs.existsSync(markerPath)) {
    errors.push("single-agent marker was not written")
  } else {
    try {
      const marker = JSON.parse(fs.readFileSync(markerPath, "utf8"))
      if (marker.observedSubagent !== agent) {
        errors.push(`single-agent marker observed ${marker.observedSubagent || "<missing>"}, expected ${agent}`)
      }
      if (!marker.callID) {
        errors.push("single-agent marker callID is missing")
      } else if (!events.some((event) => containsValue(event, marker.callID))) {
        errors.push(`single-agent marker callID ${marker.callID} was not found in current events.jsonl`)
      }
    } catch (error) {
      errors.push(`single-agent marker is not valid JSON: ${error.message}`)
    }
  }
}

for (const error of errors) console.error(`validation error: ${error}`)
process.stdout.write(errors.length ? "invalid" : "ok")
NODE
)"
if [[ "$VALIDATION_STATUS" != "ok" ]]; then
  STATUS=1
fi

printf '%s\n' "$STATUS" > "$STATUS_FILE"
printf '%s\n' "$RAW_STATUS" > "$RAW_STATUS_FILE"

printf 'Sandbox root: %s\n' "$SANDBOX_ROOT"
printf 'Worktree: %s\n' "$WORKTREE"
printf 'Generated config: %s\n' "$OPENCODE_CONFIG_DIR/opencode.json"
printf 'Generated observer plugin: %s\n' "$OBSERVER_PLUGIN"
printf 'Command: %s\n' "$COMMAND_FILE"
printf 'Metadata: %s\n' "$METADATA_FILE"
printf 'Logs: %s\n' "$LOG_FILE"
printf 'Raw events: %s\n' "$EVENTS_FILE"
printf 'Single-agent marker: %s\n' "$SINGLE_AGENT_MARKER"
printf 'OpenCode CLI exit status: %s (%s)\n' "$RAW_STATUS_FILE" "$RAW_STATUS"
printf 'Script exit status: %s (%s)\n' "$STATUS_FILE" "$STATUS"

exit "$STATUS"
