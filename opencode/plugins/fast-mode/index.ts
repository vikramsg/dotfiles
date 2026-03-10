import { appendFile, mkdir, readFile } from "node:fs/promises"
import os from "node:os"
import path from "node:path"
import type { Plugin } from "@opencode-ai/plugin"

type FastState = {
  enabled: boolean
}

const AUDIT_ENV = "OPENCODE_FAST_MODE_AUDIT"

function getPluginDataDir() {
  const xdg = process.env.XDG_DATA_HOME
  if (xdg && xdg.trim().length > 0) {
    return path.join(xdg, "opencode", "plugins")
  }
  return path.join(os.homedir(), ".local", "share", "opencode", "plugins")
}

function tier(enabled: boolean) {
  return enabled ? "priority" : "auto"
}

function auditEnabled() {
  const value = String(process.env[AUDIT_ENV] ?? "").toLowerCase().trim()
  return value === "1" || value === "true" || value === "yes"
}

function pluginLog(message: string, data?: Record<string, unknown>) {
  if (data) {
    console.error(`[fast-mode-plugin] ${message}`, data)
    return
  }
  console.error(`[fast-mode-plugin] ${message}`)
}

async function readState(filePath: string): Promise<FastState> {
  try {
    const raw = await readFile(filePath, "utf8")
    const parsed = JSON.parse(raw) as Partial<FastState>
    return { enabled: parsed.enabled === true }
  } catch (error) {
    const code = error && typeof error === "object" && "code" in error ? String((error as { code?: string }).code) : ""
    if (code && code !== "ENOENT") {
      pluginLog("failed to read state file, defaulting to OFF", {
        filePath,
        error: error instanceof Error ? error.message : String(error),
      })
    }
    return { enabled: false }
  }
}

async function appendAudit(filePath: string, line: string) {
  try {
    await mkdir(path.dirname(filePath), { recursive: true })
    await appendFile(filePath, line + "\n", "utf8")
  } catch (error) {
    pluginLog("failed to write audit log", {
      filePath,
      error: error instanceof Error ? error.message : String(error),
    })
  }
}

export const FastModePlugin: Plugin = async () => {
  const dataDir = getPluginDataDir()
  const stateFile = path.join(dataDir, "fast-mode.json")
  const auditFile = path.join(dataDir, "fast-mode.audit.log")

  return {
    "chat.params": async (input, output) => {
      try {
        const state = await readState(stateFile)
        const providerID = String((input.model as { providerID?: string })?.providerID ?? "").toLowerCase()
        const modelID = String((input.model as { modelID?: string; id?: string })?.modelID ?? input.model?.id ?? "unknown")
        const providerInfoID = String((input.provider as { info?: { id?: string }; id?: string })?.info?.id ?? input.provider?.id ?? "").toLowerCase()
        const looksOpenAI = providerID.includes("openai") || providerInfoID.includes("openai")
        if (!looksOpenAI) {
          if (auditEnabled()) {
            await appendAudit(
              auditFile,
              `${new Date().toISOString()} provider=${providerID || "unknown"} model=${modelID} fast=${state.enabled} applied=no reason=non-openai`,
            )
          }
          return
        }

        output.options.serviceTier = tier(state.enabled)
        if (auditEnabled()) {
          await appendAudit(
            auditFile,
            `${new Date().toISOString()} provider=${providerID || "unknown"} model=${modelID} fast=${state.enabled} serviceTier=${output.options.serviceTier}`,
          )
        }
      } catch (error) {
        pluginLog("chat.params failed, leaving options unchanged", {
          error: error instanceof Error ? error.message : String(error),
        })
      }
    },
  }
}

export default FastModePlugin
