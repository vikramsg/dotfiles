import { cp, readFile, readdir } from "node:fs/promises";
import path from "node:path";
import type { Path } from "./types.ts";

export function resolveFromRoot(sourceRoot: Path, filePath: Path): Path {
  return path.isAbsolute(filePath) ? filePath : path.join(sourceRoot, filePath);
}

export function isInsideDirectory(parent: Path, child: Path): boolean {
  const relative = path.relative(parent, child);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

export async function readJsonFile(file: Path, label: string): Promise<unknown> {
  let text: string;
  try {
    text = await readFile(file, "utf8");
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Could not read ${label} ${file}: ${message}`);
  }

  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`Could not parse ${label} ${file}`);
  }
}

/**
 * Copy fixture contents into the sandbox worktree rather than nesting the
 * fixture directory itself. This mirrors how a user-provided worktree starts.
 */
export async function copyDirectoryContents(sourceDir: Path, targetDir: Path): Promise<void> {
  for (const entry of await readdir(sourceDir, { withFileTypes: true })) {
    await cp(path.join(sourceDir, entry.name), path.join(targetDir, entry.name), {
      recursive: entry.isDirectory(),
      force: true,
    });
  }
}
