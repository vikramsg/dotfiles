import { describe, expect, it } from "vitest"
import { identity } from "./cli-v2.js"

describe("identity", () => {
  it("returns the input", () => {
    expect(identity("hello")).toBe("hello")
  })
})
