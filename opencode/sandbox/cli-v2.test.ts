import { describe, expect, it } from "vitest"
import { runCli } from "./cli-v2.js"

describe("cli-v2", () => {
  it("runs the hello command through cac", async () => {
    let stdout = ""
    let stderr = ""

    const status = await runCli(["node", "cli-v2", "hello"], {
      stdout: {
        write(text) {
          stdout += text
        },
      },
      stderr: {
        write(text) {
          stderr += text
        },
      },
    })

    expect(status).toBe(0)
    expect(stdout).toBe("hello world\n")
    expect(stderr).toBe("")
  })
})
