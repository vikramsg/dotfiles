import { execFile, execFileSync } from "node:child_process";
import {
  closeSync,
  existsSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  openSync,
  realpathSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { dirname, isAbsolute, relative, resolve } from "node:path";
import type { HunkExtensionAPI } from "hunkdiff/extension";

type ReviewTarget = "working" | "main" | "other";
type ReviewLayout = "auto" | "split" | "stack";

export interface CommandResult {
  error: Error | null;
  stdout: string;
  stderr: string;
}

export interface WorkflowDependencies {
  env: NodeJS.ProcessEnv;
  pid: number;
  runCommand(command: string, args: string[]): Promise<CommandResult>;
  repoRoot(cwd: string): string | null;
  isIgnored(repoRoot: string, path: string): boolean;
  writeSnapshot(path: string, snapshot: unknown): void;
}

interface ReviewExportContext {
  cwd: string;
  notify(message: string, type?: "info" | "warning" | "error"): void;
}

interface SessionReviewExport {
  review: {
    reviewNotes?: readonly unknown[];
  };
}

const DEFAULT_REVIEW_PATH = ".agents/reviews/hunk-review.json";
const REVIEW_DIRECTORY = ".agents/reviews";

function getHunkBin(env: NodeJS.ProcessEnv): string {
  if (env.HUNK_BIN_PATH) return env.HUNK_BIN_PATH;
  const standardPaths = [
    "/home/linuxbrew/.linuxbrew/bin/hunk",
    "/opt/homebrew/bin/hunk",
    "/usr/local/bin/hunk",
  ];
  return standardPaths.find(existsSync) ?? "hunk";
}

function runCommand(command: string, args: string[]): Promise<CommandResult> {
  return new Promise((complete) => {
    execFile(command, args, { encoding: "utf8" }, (error, stdout, stderr) => {
      complete({ error, stdout, stderr });
    });
  });
}

export function findRepoRoot(cwd: string): string | null {
  try {
    return execFileSync("git", ["-C", cwd, "rev-parse", "--show-toplevel"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return null;
  }
}

export function isGitIgnored(repoRoot: string, path: string): boolean {
  try {
    execFileSync("git", ["-C", repoRoot, "check-ignore", "-q", "--", path], {
      stdio: "ignore",
    });
    return true;
  } catch {
    return false;
  }
}

function nearestExistingPath(path: string): string {
  let current = path;
  while (!existsSync(current)) {
    const parent = dirname(current);
    if (parent === current) return current;
    current = parent;
  }
  return current;
}

export function resolveReviewPath(repoRoot: string, configuredPath: unknown): string {
  const path =
    typeof configuredPath === "string" && configuredPath.trim()
      ? configuredPath.trim()
      : DEFAULT_REVIEW_PATH;
  if (isAbsolute(path)) {
    throw new Error("review_path must be relative to the repository root");
  }

  const canonicalRoot = realpathSync(repoRoot);
  const outputPath = resolve(canonicalRoot, path);
  if (existsSync(outputPath) && lstatSync(outputPath).isSymbolicLink()) {
    throw new Error("review_path must not be a symbolic link");
  }
  const existingAncestor = nearestExistingPath(outputPath);
  const canonicalOutput = resolve(
    realpathSync(existingAncestor),
    relative(existingAncestor, outputPath),
  );
  const reviewRoot = resolve(canonicalRoot, REVIEW_DIRECTORY);
  const reviewRootAncestor = nearestExistingPath(reviewRoot);
  const canonicalReviewRoot = resolve(
    realpathSync(reviewRootAncestor),
    relative(reviewRootAncestor, reviewRoot),
  );
  const reviewRootOffset = relative(canonicalRoot, canonicalReviewRoot);
  if (
    reviewRootOffset === "" ||
    reviewRootOffset.startsWith("..") ||
    isAbsolute(reviewRootOffset)
  ) {
    throw new Error(`${REVIEW_DIRECTORY} must stay inside the repository root`);
  }
  const offset = relative(canonicalReviewRoot, canonicalOutput);
  if (offset === "" || offset.startsWith("..") || isAbsolute(offset)) {
    throw new Error(`review_path must stay inside ${REVIEW_DIRECTORY}`);
  }
  return canonicalOutput;
}

export function writeReviewSnapshot(path: string, snapshot: unknown): void {
  mkdirSync(dirname(path), { recursive: true });
  const temporaryPath = `${path}.${process.pid}.${Date.now()}.tmp`;
  let descriptor: number | undefined;
  let ownsTemporaryPath = false;
  try {
    descriptor = openSync(temporaryPath, "wx", 0o600);
    ownsTemporaryPath = true;
    writeFileSync(descriptor, `${JSON.stringify(snapshot, null, 2)}\n`, "utf8");
    fsyncSync(descriptor);
    closeSync(descriptor);
    descriptor = undefined;
    renameSync(temporaryPath, path);
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
    if (ownsTemporaryPath) rmSync(temporaryPath, { force: true });
  }
}

const defaultDependencies: WorkflowDependencies = {
  env: process.env,
  pid: process.pid,
  runCommand,
  repoRoot: findRepoRoot,
  isIgnored: isGitIgnored,
  writeSnapshot: writeReviewSnapshot,
};

function commandFailure(result: CommandResult): string {
  return result.stderr.trim() || result.error?.message || "unknown error";
}

export function createReviewWorkflowExtension(
  dependencies: WorkflowDependencies = defaultDependencies,
) {
  return function reviewWorkflow(hunk: HunkExtensionAPI) {
    let currentTarget: ReviewTarget =
      dependencies.env.HUNK_REVIEW_TARGET === "main" ? "main" : "working";
    let currentLayout: ReviewLayout = "stack";
    let exportQueue = Promise.resolve();
    const configuredReviewPath = hunk.config.review_path;

    async function sessionSelector(repoRoot: string): Promise<string[]> {
      const hunkBin = getHunkBin(dependencies.env);
      const sessions = await dependencies.runCommand(hunkBin, ["session", "list", "--json"]);
      if (!sessions.error) {
        try {
          const parsed = JSON.parse(sessions.stdout) as {
            sessions?: Array<{ sessionId?: unknown; pid?: unknown }>;
          };
          const ownSession = parsed.sessions?.find(
            (session) => session.pid === dependencies.pid && typeof session.sessionId === "string",
          );
          if (ownSession) return [ownSession.sessionId as string];
        } catch {
          // Fall back to the repository selector for older or malformed list output.
        }
      }
      return ["--repo", repoRoot];
    }

    async function reload(
      ctx: {
        cwd: string;
        notify(message: string, type?: "info" | "warning" | "error"): void;
      },
      args: string[],
    ) {
      const repoRoot = dependencies.repoRoot(ctx.cwd);
      if (!repoRoot) {
        ctx.notify("Hunk review target switching requires a Git repository", "error");
        return false;
      }
      const hunkBin = getHunkBin(dependencies.env);
      const selector = await sessionSelector(repoRoot);

      const result = await dependencies.runCommand(hunkBin, [
        "session",
        "reload",
        ...selector,
        "--",
        ...args,
      ]);
      if (result.error) {
        ctx.notify(`Failed to switch review target: ${commandFailure(result)}`, "error");
        return false;
      }
      ctx.notify(`Reviewing: hunk ${args.join(" ")}`);
      return true;
    }

    hunk.registerCommand(
      { id: "toggle-target", title: "Toggle working tree / main", key: "B" },
      async (ctx) => {
        const nextTarget: ReviewTarget = currentTarget === "working" ? "main" : "working";
        const args = nextTarget === "main" ? ["diff", "main..."] : ["diff"];
        if (await reload(ctx, args)) currentTarget = nextTarget;
      },
    );

    hunk.registerCommand(
      { id: "choose-target", title: "Choose review target…", key: "ctrl+b" },
      async (ctx) => {
        const choices = [
          {
            label: "Uncommitted changes (working tree)",
            args: ["diff"],
            target: "working" as const,
          },
          {
            label: "Branch diff vs main (main...)",
            args: ["diff", "main..."],
            target: "main" as const,
          },
          {
            label: "Branch diff vs origin/main (origin/main...)",
            args: ["diff", "origin/main..."],
            target: "other" as const,
          },
          {
            label: "Staged changes only (--staged)",
            args: ["diff", "--staged"],
            target: "other" as const,
          },
          {
            label: "Last commit (HEAD)",
            args: ["show", "HEAD"],
            target: "other" as const,
          },
        ];
        const customLabel = "Custom revision / range…";
        const picked = await ctx.dialogs.select({
          title: "Choose Review Target",
          options: [...choices.map((choice) => choice.label), customLabel],
        });
        if (picked === null) return;

        const choice = choices.find((candidate) => candidate.label === picked);
        if (choice) {
          if (await reload(ctx, choice.args)) currentTarget = choice.target;
          return;
        }

        const input = await ctx.dialogs.input({
          title: "Custom Revision / Range",
          placeholder: "main...HEAD or HEAD~2",
        });
        if (input === null || input.trim() === "") return;
        const target = input.trim();
        if (/\s/.test(target) || target.startsWith("-")) {
          ctx.notify("Enter one revision or revision range without spaces", "warning");
          return;
        }
        if (await reload(ctx, ["diff", target])) currentTarget = "other";
      },
    );

    hunk.registerCommand(
      { id: "toggle-layout", title: "Toggle stack / split layout", key: "t" },
      (ctx) => {
        const nextLayout = currentLayout === "split" ? "stack" : "split";
        const command = nextLayout === "split" ? "hunk.view.layoutSplit" : "hunk.view.layoutStack";
        if (ctx.commands.execute(command)) currentLayout = nextLayout;
      },
    );

    async function exportReview(ctx: ReviewExportContext) {
      const repoRoot = dependencies.repoRoot(ctx.cwd);
      if (!repoRoot) {
        ctx.notify("Saving review comments requires a Git repository", "error");
        return;
      }

      try {
        const canonicalRoot = realpathSync(repoRoot);
        const outputPath = resolveReviewPath(canonicalRoot, configuredReviewPath);
        const relativePath = relative(canonicalRoot, outputPath);
        if (!dependencies.isIgnored(canonicalRoot, relativePath)) {
          ctx.notify(
            `Refusing to save review comments because ${relativePath} is not ignored by Git`,
            "error",
          );
          return;
        }

        const hunkBin = getHunkBin(dependencies.env);
        const selector = await sessionSelector(canonicalRoot);
        const result = await dependencies.runCommand(hunkBin, [
          "session",
          "review",
          ...selector,
          "--include-notes",
          "--json",
        ]);
        if (result.error) {
          throw new Error(commandFailure(result));
        }
        const exported = JSON.parse(result.stdout) as SessionReviewExport;
        if (!exported.review || !Array.isArray(exported.review.reviewNotes)) {
          throw new Error("Hunk returned an invalid live review export");
        }
        dependencies.writeSnapshot(outputPath, exported);
        const noteCount = exported.review.reviewNotes.length;
        ctx.notify(
          `Saved ${noteCount} review ${noteCount === 1 ? "comment" : "comments"} to ${relativePath}`,
        );
      } catch (error) {
        ctx.notify(
          `Failed to save review comments: ${error instanceof Error ? error.message : String(error)}`,
          "error",
        );
      }
    }

    hunk.on("note_changed", async (_event, ctx) => {
      exportQueue = exportQueue.then(() => exportReview(ctx));
      await exportQueue;
    });

    hunk.on("layout_changed", ({ layout }) => {
      currentLayout = layout;
    });
  };
}

export default createReviewWorkflowExtension();
