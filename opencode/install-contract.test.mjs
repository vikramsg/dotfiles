import test from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"

const currentFile = fileURLToPath(import.meta.url)
const opencodeDir = path.dirname(currentFile)
const repoRoot = path.resolve(opencodeDir, "..")
const readmePath = path.join(opencodeDir, "README.md")
const justfilePath = path.join(repoRoot, "justfile")

function makeHome() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "opencode-install-contract-home-"))
}

test("restart contract is documented in README and justfile", () => {
  const readme = fs.readFileSync(readmePath, "utf8")
  const justfile = fs.readFileSync(justfilePath, "utf8")

  for (const source of [readme, justfile]) {
    assert.match(source, /newly started/i)
    assert.match(source, /already-running/i)
    assert.match(source, /restart/i)
  }
})

test("just opencode prints restart guidance for already-running sessions", () => {
  const tempHome = makeHome()
  const result = spawnSync("just", ["opencode"], {
    cwd: repoRoot,
    env: {
      ...process.env,
      HOME: tempHome,
    },
    stdio: "pipe",
    encoding: "utf8",
    timeout: 120000,
  })

  if (result.error) {
    throw result.error
  }

  assert.equal(result.status, 0, result.stderr || result.stdout)

  const output = `${result.stdout}\n${result.stderr}`
  assert.match(output, /newly started/i)
  assert.match(output, /already-running/i)
  assert.match(output, /restart/i)

  assert.equal(fs.existsSync(path.join(tempHome, ".config", "opencode", "plugins", "orchestration-state.js")), true)
  assert.equal(fs.existsSync(path.join(tempHome, ".config", "opencode", "opencode.json")), true)
})
