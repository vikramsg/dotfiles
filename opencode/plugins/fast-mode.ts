import { appendFile, mkdir, readFile } from "node:fs/promises"
import path from "node:path"
import type { Plugin } from "@opencode-ai/plugin"

type FastState = {
  enabled: boolean
}

function tier(enabled: boolean) {
  return enabled ? "priority" : "auto"
}

async function loadState(filePath: string): Promise<FastState> {
  try {
    const raw = await readFile(filePath, "utf8")
    const parsed = JSON.parse(raw) as Partial<FastState>
    return { enabled: parsed.enabled === true }
  } catch {
    return { enabled: false }
  }
}

async function appendAudit(filePath: string, line: string) {
  await mkdir(path.dirname(filePath), { recursive: true })
  await appendFile(filePath, line + "\n", "utf8")
}

export const FastModePlugin: Plugin = async ({ worktree }) => {
  const stateFile = path.join(worktree, ".opencode", "fast-mode.json")
  const auditFile = path.join(worktree, ".opencode", "fast-mode.audit.log")

  return {
    "chat.params": async (input, output) => {
      const state = await loadState(stateFile)
      const providerID = String((input.model as { providerID?: string })?.providerID ?? "").toLowerCase()
      const modelID = String((input.model as { modelID?: string; id?: string })?.modelID ?? input.model?.id ?? "unknown")
      const providerInfoID = String((input.provider as { info?: { id?: string }; id?: string })?.info?.id ?? input.provider?.id ?? "").toLowerCase()
      const looksOpenAI = providerID.includes("openai") || providerInfoID.includes("openai")
      if (!looksOpenAI) {
        await appendAudit(
          auditFile,
          `${new Date().toISOString()} provider=${providerID || "unknown"} model=${modelID} fast=${state.enabled} applied=no reason=non-openai`,
        )
        return
      }

      output.options.serviceTier = tier(state.enabled)
      await appendAudit(
        auditFile,
        `${new Date().toISOString()} provider=${providerID || "unknown"} model=${modelID} fast=${state.enabled} serviceTier=${output.options.serviceTier}`,
      )
    },
  }
}

export default FastModePlugin
