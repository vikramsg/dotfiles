import { mkdir, mkdtemp, readFile, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { copyScenarioFixture, loadScenario, readScenarioRecipe, ScenarioValidationError } from "./scenario.ts";

async function tempDir(name = "cli-v2-scenario-") {
  return mkdtemp(path.join(os.tmpdir(), name));
}

async function writeScenarioFixture(root: string, recipe: Record<string, unknown> = {}) {
  const scenarioDir = path.join(root, "scenario");
  const fixtureDir = path.join(scenarioDir, "worktree");

  await mkdir(fixtureDir, { recursive: true });
  await writeFile(path.join(scenarioDir, "prompt.md"), "Scenario prompt\n");
  await writeFile(path.join(fixtureDir, "README.md"), "fixture readme\n");
  await writeFile(
    path.join(scenarioDir, "scenario.json"),
    JSON.stringify(
      {
        name: "custom-scenario",
        agent: "custom-agent",
        agentFile: "fixtures/agents/custom-agent.md",
        promptFile: "prompt.md",
        fixtureDir: "worktree",
        ...recipe,
      },
      null,
      2,
    ),
  );

  return scenarioDir;
}

describe("scenario", () => {
  it("reads and validates a scenario recipe", async () => {
    const root = await tempDir();
    const scenarioDir = await writeScenarioFixture(root);

    await expect(readScenarioRecipe(scenarioDir)).resolves.toEqual({
      name: "custom-scenario",
      agent: "custom-agent",
      agentFile: "fixtures/agents/custom-agent.md",
      promptFile: "prompt.md",
      fixtureDir: "worktree",
    });
  });

  it("loads scenario paths without depending on sandbox internals", async () => {
    const root = await tempDir();
    const cliRoot = path.join(root, "cli-v2");
    const defaultConfigFile = path.join(root, "opencode.json");
    const scenarioDir = await writeScenarioFixture(root);

    const scenario = await loadScenario({ scenarioDir, cliRoot, defaultConfigFile });

    expect(scenario).toEqual({
      name: "custom-scenario",
      agent: "custom-agent",
      prompt: "Scenario prompt\n",
      promptFile: path.join(scenarioDir, "prompt.md"),
      sourceConfigFile: defaultConfigFile,
      sourceAgentFile: path.join(cliRoot, "fixtures", "agents", "custom-agent.md"),
      fixtureDir: path.join(scenarioDir, "worktree"),
    });
  });

  it("resolves explicit config relative to the CLI v2 root unless absolute", async () => {
    const root = await tempDir();
    const cliRoot = path.join(root, "cli-v2");
    const defaultConfigFile = path.join(root, "opencode.json");
    const relativeScenarioDir = await writeScenarioFixture(root, { config: "fixtures/config/opencode.json" });
    const absoluteConfig = path.join(root, "absolute-opencode.json");
    const absoluteScenarioDir = await writeScenarioFixture(path.join(root, "absolute"), { config: absoluteConfig });

    await expect(loadScenario({ scenarioDir: relativeScenarioDir, cliRoot, defaultConfigFile })).resolves.toMatchObject({
      sourceConfigFile: path.join(cliRoot, "fixtures", "config", "opencode.json"),
    });
    await expect(loadScenario({ scenarioDir: absoluteScenarioDir, cliRoot, defaultConfigFile })).resolves.toMatchObject({
      sourceConfigFile: absoluteConfig,
    });
  });

  it("copies optional scenario fixture contents into a plain worktree path", async () => {
    const root = await tempDir();
    const cliRoot = path.join(root, "cli-v2");
    const defaultConfigFile = path.join(root, "opencode.json");
    const scenarioDir = await writeScenarioFixture(root);
    const worktree = path.join(root, "prepared-worktree");
    const scenario = await loadScenario({ scenarioDir, cliRoot, defaultConfigFile });

    await mkdir(worktree, { recursive: true });
    await copyScenarioFixture(scenario, worktree);

    expect(await readFile(path.join(worktree, "README.md"), "utf8")).toBe("fixture readme\n");
  });

  it.each([
    ["absolute", (root: string) => path.join(root, "outside-prompt.md"), "Scenario promptFile must be relative"],
    ["traversal", () => "../outside-prompt.md", "Scenario promptFile escapes scenario directory"],
  ])("rejects %s scenario prompt paths", async (_name, promptFile, message) => {
    const root = await tempDir();
    const cliRoot = path.join(root, "cli-v2");
    const defaultConfigFile = path.join(root, "opencode.json");

    await writeFile(path.join(root, "outside-prompt.md"), "outside prompt\n");
    const scenarioDir = await writeScenarioFixture(root, { promptFile: promptFile(root) });

    await expect(loadScenario({ scenarioDir, cliRoot, defaultConfigFile })).rejects.toThrow(ScenarioValidationError);
    await expect(loadScenario({ scenarioDir, cliRoot, defaultConfigFile })).rejects.toThrow(message);
  });

  it("rejects promptFile symlinks that point outside the scenario directory", async () => {
    const root = await tempDir();
    const cliRoot = path.join(root, "cli-v2");
    const defaultConfigFile = path.join(root, "opencode.json");
    const outsidePrompt = path.join(root, "outside-prompt.md");
    const scenarioDir = await writeScenarioFixture(root, { promptFile: "prompt-link.md" });

    await writeFile(outsidePrompt, "outside prompt\n");
    await symlink(outsidePrompt, path.join(scenarioDir, "prompt-link.md"));

    await expect(loadScenario({ scenarioDir, cliRoot, defaultConfigFile })).rejects.toThrow(ScenarioValidationError);
    await expect(loadScenario({ scenarioDir, cliRoot, defaultConfigFile })).rejects.toThrow(
      `Scenario promptFile cannot be a symlink: ${path.join(scenarioDir, "prompt-link.md")}`,
    );
  });

  it("rejects prompt paths that escape through a symlinked parent directory", async () => {
    const root = await tempDir();
    const cliRoot = path.join(root, "cli-v2");
    const defaultConfigFile = path.join(root, "opencode.json");
    const outsideDir = path.join(root, "outside-prompts");
    const scenarioDir = await writeScenarioFixture(root, { promptFile: "linked-prompts/prompt.md" });

    await mkdir(outsideDir, { recursive: true });
    await writeFile(path.join(outsideDir, "prompt.md"), "outside prompt\n");
    await symlink(outsideDir, path.join(scenarioDir, "linked-prompts"), "dir");

    await expect(loadScenario({ scenarioDir, cliRoot, defaultConfigFile })).rejects.toThrow(ScenarioValidationError);
    await expect(loadScenario({ scenarioDir, cliRoot, defaultConfigFile })).rejects.toThrow(
      "Scenario promptFile escapes scenario directory",
    );
  });

  it("wraps missing scenario prompt files as validation errors", async () => {
    const root = await tempDir();
    const cliRoot = path.join(root, "cli-v2");
    const defaultConfigFile = path.join(root, "opencode.json");
    const scenarioDir = await writeScenarioFixture(root, { promptFile: "missing.md" });
    const missingPrompt = path.join(scenarioDir, "missing.md");

    await expect(loadScenario({ scenarioDir, cliRoot, defaultConfigFile })).rejects.toThrow(ScenarioValidationError);
    await expect(loadScenario({ scenarioDir, cliRoot, defaultConfigFile })).rejects.toThrow(
      `Could not read scenario prompt file ${missingPrompt}`,
    );
  });

  it.each([
    ["absolute", (root: string) => path.join(root, "outside-worktree"), "Scenario fixtureDir must be relative"],
    ["traversal", () => "../outside-worktree", "Scenario fixtureDir escapes scenario directory"],
  ])("rejects %s scenario fixture paths", async (_name, fixtureDir, message) => {
    const root = await tempDir();
    const cliRoot = path.join(root, "cli-v2");
    const defaultConfigFile = path.join(root, "opencode.json");

    await mkdir(path.join(root, "outside-worktree"), { recursive: true });
    const scenarioDir = await writeScenarioFixture(root, { fixtureDir: fixtureDir(root) });

    await expect(loadScenario({ scenarioDir, cliRoot, defaultConfigFile })).rejects.toThrow(ScenarioValidationError);
    await expect(loadScenario({ scenarioDir, cliRoot, defaultConfigFile })).rejects.toThrow(message);
  });

  it("rejects fixtureDir symlinks that point outside the scenario directory", async () => {
    const root = await tempDir();
    const cliRoot = path.join(root, "cli-v2");
    const defaultConfigFile = path.join(root, "opencode.json");
    const outsideFixture = path.join(root, "outside-worktree");
    const scenarioDir = await writeScenarioFixture(root, { fixtureDir: "worktree-link" });

    await mkdir(outsideFixture, { recursive: true });
    await symlink(outsideFixture, path.join(scenarioDir, "worktree-link"), "dir");

    await expect(loadScenario({ scenarioDir, cliRoot, defaultConfigFile })).rejects.toThrow(ScenarioValidationError);
    await expect(loadScenario({ scenarioDir, cliRoot, defaultConfigFile })).rejects.toThrow(
      `Scenario fixtureDir cannot be a symlink: ${path.join(scenarioDir, "worktree-link")}`,
    );
  });

  it("rejects symlinks inside the fixture tree during scenario loading", async () => {
    const root = await tempDir();
    const cliRoot = path.join(root, "cli-v2");
    const defaultConfigFile = path.join(root, "opencode.json");
    const outsideFixtureFile = path.join(root, "outside-fixture.txt");
    const scenarioDir = await writeScenarioFixture(root);
    const fixtureLink = path.join(scenarioDir, "worktree", "outside-fixture-link.txt");

    await writeFile(outsideFixtureFile, "outside fixture\n");
    await symlink(outsideFixtureFile, fixtureLink);

    await expect(loadScenario({ scenarioDir, cliRoot, defaultConfigFile })).rejects.toThrow(ScenarioValidationError);
    await expect(loadScenario({ scenarioDir, cliRoot, defaultConfigFile })).rejects.toThrow(
      `Scenario fixture contains symlink: ${fixtureLink}`,
    );
  });

  it("rechecks fixture tree symlinks before copying", async () => {
    const root = await tempDir();
    const cliRoot = path.join(root, "cli-v2");
    const defaultConfigFile = path.join(root, "opencode.json");
    const outsideFixtureFile = path.join(root, "late-outside-fixture.txt");
    const scenarioDir = await writeScenarioFixture(root);
    const scenario = await loadScenario({ scenarioDir, cliRoot, defaultConfigFile });
    const worktree = path.join(root, "prepared-worktree");
    const fixtureLink = path.join(scenarioDir, "worktree", "late-outside-fixture-link.txt");

    await mkdir(worktree, { recursive: true });
    await writeFile(outsideFixtureFile, "outside fixture\n");
    await symlink(outsideFixtureFile, fixtureLink);

    await expect(copyScenarioFixture(scenario, worktree)).rejects.toThrow(ScenarioValidationError);
    await expect(copyScenarioFixture(scenario, worktree)).rejects.toThrow(
      `Could not copy scenario fixture ${scenario.fixtureDir} into ${worktree}: Scenario fixture contains symlink: ${fixtureLink}`,
    );
  });

  it("rejects missing fixture directories during scenario loading", async () => {
    const root = await tempDir();
    const cliRoot = path.join(root, "cli-v2");
    const defaultConfigFile = path.join(root, "opencode.json");
    const scenarioDir = await writeScenarioFixture(root, { fixtureDir: "missing-worktree" });
    const missingFixture = path.join(scenarioDir, "missing-worktree");

    await expect(loadScenario({ scenarioDir, cliRoot, defaultConfigFile })).rejects.toThrow(ScenarioValidationError);
    await expect(loadScenario({ scenarioDir, cliRoot, defaultConfigFile })).rejects.toThrow(
      `Could not stat scenario fixture directory ${missingFixture}`,
    );
  });

  it("rejects fixture paths that are not directories during scenario loading", async () => {
    const root = await tempDir();
    const cliRoot = path.join(root, "cli-v2");
    const defaultConfigFile = path.join(root, "opencode.json");
    const scenarioDir = await writeScenarioFixture(root, { fixtureDir: "fixture-file" });
    const fixtureFile = path.join(scenarioDir, "fixture-file");

    await writeFile(fixtureFile, "not a directory\n");

    await expect(loadScenario({ scenarioDir, cliRoot, defaultConfigFile })).rejects.toThrow(ScenarioValidationError);
    await expect(loadScenario({ scenarioDir, cliRoot, defaultConfigFile })).rejects.toThrow(
      `Scenario fixture path is not a directory: ${fixtureFile}`,
    );
  });

  it("wraps fixture copy failures as scenario validation errors", async () => {
    const root = await tempDir();
    const cliRoot = path.join(root, "cli-v2");
    const defaultConfigFile = path.join(root, "opencode.json");
    const scenarioDir = await writeScenarioFixture(root);
    const scenario = await loadScenario({ scenarioDir, cliRoot, defaultConfigFile });
    const worktree = path.join(root, "worktree-file");

    await writeFile(worktree, "not a directory\n");

    await expect(copyScenarioFixture(scenario, worktree)).rejects.toThrow(ScenarioValidationError);
    await expect(copyScenarioFixture(scenario, worktree)).rejects.toThrow(
      `Could not copy scenario fixture ${scenario.fixtureDir} into ${worktree}`,
    );
  });

  it("throws scenario validation errors for missing, malformed, or invalid recipes", async () => {
    const root = await tempDir();
    const missingDir = path.join(root, "missing");
    const malformedDir = path.join(root, "malformed");
    const invalidDir = path.join(root, "invalid");

    await mkdir(malformedDir, { recursive: true });
    await mkdir(invalidDir, { recursive: true });
    await writeFile(path.join(malformedDir, "scenario.json"), "{");
    await writeFile(path.join(invalidDir, "scenario.json"), JSON.stringify({ name: "missing fields" }));

    await expect(readScenarioRecipe(missingDir)).rejects.toThrow(ScenarioValidationError);
    await expect(readScenarioRecipe(malformedDir)).rejects.toThrow(ScenarioValidationError);
    await expect(readScenarioRecipe(invalidDir)).rejects.toThrow(ScenarioValidationError);
  });
});
