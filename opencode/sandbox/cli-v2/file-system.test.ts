import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { copyDirectoryContents, isInsideDirectory, readJsonFile, resolveFromRoot } from "./file-system.ts";

async function tempDir(name = "cli-v2-fs-") {
  return mkdtemp(path.join(os.tmpdir(), name));
}

describe("file-system helpers", () => {
  it("resolves relative paths from a root and preserves absolute paths", async () => {
    const root = await tempDir();
    const absolute = path.join(root, "already-absolute.json");

    expect(resolveFromRoot(root, "nested/file.json")).toBe(path.join(root, "nested", "file.json"));
    expect(resolveFromRoot(root, absolute)).toBe(absolute);
  });

  it("detects descendants without accepting sibling escapes", async () => {
    const parent = await tempDir();

    expect(isInsideDirectory(parent, parent)).toBe(true);
    expect(isInsideDirectory(parent, path.join(parent, "child", "file.txt"))).toBe(true);
    expect(isInsideDirectory(parent, path.join(path.dirname(parent), `${path.basename(parent)}-sibling`))).toBe(false);
    expect(isInsideDirectory(parent, path.resolve(parent, "..", "escape.txt"))).toBe(false);
  });

  it("reads JSON with label-specific read and parse errors", async () => {
    const root = await tempDir();
    const valid = path.join(root, "valid.json");
    const malformed = path.join(root, "malformed.json");
    const missing = path.join(root, "missing.json");

    await writeFile(valid, JSON.stringify({ ok: true }));
    await writeFile(malformed, "{");

    await expect(readJsonFile(valid, "scenario file")).resolves.toEqual({ ok: true });
    await expect(readJsonFile(malformed, "scenario file")).rejects.toThrow(`Could not parse scenario file ${malformed}`);
    await expect(readJsonFile(missing, "scenario file")).rejects.toThrow(`Could not read scenario file ${missing}:`);
  });

  it("copies directory contents without nesting the source directory", async () => {
    const root = await tempDir();
    const source = path.join(root, "fixture");
    const target = path.join(root, "worktree");

    await mkdir(path.join(source, "nested"), { recursive: true });
    await mkdir(target, { recursive: true });
    await writeFile(path.join(source, "README.md"), "fixture readme\n");
    await writeFile(path.join(source, "nested", "file.txt"), "nested file\n");

    await copyDirectoryContents(source, target);

    expect(await readFile(path.join(target, "README.md"), "utf8")).toBe("fixture readme\n");
    expect(await readFile(path.join(target, "nested", "file.txt"), "utf8")).toBe("nested file\n");
    await expect(readFile(path.join(target, "fixture", "README.md"), "utf8")).rejects.toThrow();
  });
});
