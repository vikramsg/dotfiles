import { lstat, readFile, readdir, realpath, stat } from "node:fs/promises";
import type { Dirent } from "node:fs";
import path from "node:path";
import { z } from "zod";
import { copyDirectoryContents, isInsideDirectory, readJsonFile, resolveFromRoot } from "./file-system.ts";
import type { Path } from "./types.ts";

const ScenarioSchema = z.object({
  name: z.string().min(1),
  agent: z.string().min(1),
  agentFile: z.string().min(1),
  promptFile: z.string().min(1),
  fixtureDir: z.string().min(1).optional(),
  config: z.string().min(1).optional(),
});

export type ScenarioRecipe = z.infer<typeof ScenarioSchema>;

export type LoadedScenario = {
  name: string;
  agent: string;
  prompt: string;
  promptFile: Path;
  sourceConfigFile: Path;
  sourceAgentFile: Path;
  fixtureDir?: Path;
};

export class ScenarioValidationError extends Error {
  override name = "ScenarioValidationError";
}

export type LoadScenarioArgs = {
  scenarioDir: Path;
  cliRoot: Path;
  defaultConfigFile: Path;
};

/**
 * Scenario-owned paths must stay relative to the scenario directory so a saved
 * run recipe cannot read prompts or copy fixtures from elsewhere on disk.
 */
function resolveScenarioRelativePath(scenarioDir: Path, fieldName: "promptFile" | "fixtureDir", value: Path): Path {
  if (path.isAbsolute(value)) {
    throw new ScenarioValidationError(`Scenario ${fieldName} must be relative: ${value}`);
  }

  const resolvedScenarioDir = path.resolve(scenarioDir);
  const resolved = path.resolve(resolvedScenarioDir, value);
  if (!isInsideDirectory(resolvedScenarioDir, resolved)) {
    throw new ScenarioValidationError(`Scenario ${fieldName} escapes scenario directory: ${value} -> ${resolved}`);
  }

  return resolved;
}

function scenarioPathFailureMessage(fieldName: "promptFile" | "fixtureDir", candidate: Path, message: string): string {
  if (fieldName === "promptFile") {
    return `Could not read scenario prompt file ${candidate}: ${message}`;
  }

  return `Could not stat scenario fixture directory ${candidate}: ${message}`;
}

/**
 * Scenario-owned paths are checked lexically first for clear user errors, then
 * checked with realpath so symlinked parent directories cannot escape the real
 * scenario root.
 */
async function validateScenarioOwnedPath(
  scenarioDir: Path,
  realScenarioDir: Path,
  fieldName: "promptFile" | "fixtureDir",
  value: Path,
): Promise<Path> {
  const candidate = resolveScenarioRelativePath(scenarioDir, fieldName, value);
  let candidateStat: Awaited<ReturnType<typeof lstat>>;

  try {
    candidateStat = await lstat(candidate);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new ScenarioValidationError(scenarioPathFailureMessage(fieldName, candidate, message));
  }

  if (candidateStat.isSymbolicLink()) {
    throw new ScenarioValidationError(`Scenario ${fieldName} cannot be a symlink: ${candidate}`);
  }

  let realCandidate: Path;
  try {
    realCandidate = await realpath(candidate);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new ScenarioValidationError(scenarioPathFailureMessage(fieldName, candidate, message));
  }

  if (!isInsideDirectory(realScenarioDir, realCandidate)) {
    throw new ScenarioValidationError(`Scenario ${fieldName} escapes scenario directory: ${value} -> ${realCandidate}`);
  }

  return realCandidate;
}

/**
 * Fixtures are copied into an isolated worktree; reject symlinks rather than
 * copying links that may still resolve outside the sandbox.
 */
async function assertFixtureTreeHasNoSymlinks(fixtureDir: Path): Promise<void> {
  let entries: Dirent<string>[];
  try {
    entries = await readdir(fixtureDir, { withFileTypes: true });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new ScenarioValidationError(`Could not inspect scenario fixture directory ${fixtureDir}: ${message}`);
  }

  for (const entry of entries) {
    const entryPath = path.join(fixtureDir, entry.name);
    if (entry.isSymbolicLink()) {
      throw new ScenarioValidationError(`Scenario fixture contains symlink: ${entryPath}`);
    }

    if (entry.isDirectory()) {
      await assertFixtureTreeHasNoSymlinks(entryPath);
    }
  }
}

/**
 * A scenario is intentionally only a saved run recipe. It does not contain
 * assertions, expected output, scoring, or any evaluation contract.
 */
export async function readScenarioRecipe(scenarioDir: Path): Promise<ScenarioRecipe> {
  const scenarioFile = path.join(scenarioDir, "scenario.json");
  let parsed: unknown;
  try {
    parsed = await readJsonFile(scenarioFile, "scenario file");
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new ScenarioValidationError(message);
  }

  const result = ScenarioSchema.safeParse(parsed);
  if (!result.success) {
    throw new ScenarioValidationError(`Could not parse scenario file ${scenarioFile}`);
  }

  return result.data;
}

export async function loadScenario(args: LoadScenarioArgs): Promise<LoadedScenario> {
  const recipe = await readScenarioRecipe(args.scenarioDir);
  const realScenarioDir = await realpath(args.scenarioDir);
  const promptFile = await validateScenarioOwnedPath(args.scenarioDir, realScenarioDir, "promptFile", recipe.promptFile);
  let prompt: string;
  try {
    prompt = await readFile(promptFile, "utf8");
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new ScenarioValidationError(`Could not read scenario prompt file ${promptFile}: ${message}`);
  }

  const fixtureDir = recipe.fixtureDir
    ? await validateScenarioOwnedPath(args.scenarioDir, realScenarioDir, "fixtureDir", recipe.fixtureDir)
    : undefined;

  if (fixtureDir) {
    let fixtureStat: Awaited<ReturnType<typeof stat>>;
    try {
      fixtureStat = await stat(fixtureDir);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      throw new ScenarioValidationError(`Could not stat scenario fixture directory ${fixtureDir}: ${message}`);
    }

    if (!fixtureStat.isDirectory()) {
      throw new ScenarioValidationError(`Scenario fixture path is not a directory: ${fixtureDir}`);
    }

    await assertFixtureTreeHasNoSymlinks(fixtureDir);
  }

  return {
    name: recipe.name,
    agent: recipe.agent,
    prompt,
    promptFile,
    sourceConfigFile: recipe.config ? resolveFromRoot(args.cliRoot, recipe.config) : args.defaultConfigFile,
    sourceAgentFile: resolveFromRoot(args.cliRoot, recipe.agentFile),
    fixtureDir,
  };
}

export async function copyScenarioFixture(scenario: LoadedScenario, worktree: Path): Promise<void> {
  if (!scenario.fixtureDir) return;

  try {
    await assertFixtureTreeHasNoSymlinks(scenario.fixtureDir);
    await copyDirectoryContents(scenario.fixtureDir, worktree);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new ScenarioValidationError(`Could not copy scenario fixture ${scenario.fixtureDir} into ${worktree}: ${message}`);
  }
}
