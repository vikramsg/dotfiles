import { afterEach, describe, expect, test } from "bun:test";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ExtensionReviewSnapshot } from "hunkdiff/extension";
import {
  createReviewWorkflowExtension,
  resolveReviewPath,
  writeReviewSnapshot,
  type WorkflowDependencies,
} from "../extensions/review-workflow";

const temporaryDirectories: string[] = [];

function temporaryDirectory() {
  const directory = mkdtempSync(join(tmpdir(), "hunk-review-workflow-"));
  temporaryDirectories.push(directory);
  return directory;
}

afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    rmSync(directory, { recursive: true, force: true });
  }
});

function snapshot(notes: ExtensionReviewSnapshot["notes"] = []): ExtensionReviewSnapshot {
  return {
    generation: "generation:test:1",
    stateRevision: 4,
    files: [
      {
        fileKey: "file:README.md",
        runtimeId: "README.md",
        path: "README.md",
        changeKind: "change",
        stats: { additions: 1, deletions: 0, truncated: false },
        flags: { untracked: false, binary: false, tooLarge: false, partial: false },
        contentIdentity: "content:readme",
      },
    ],
    notes,
  };
}

function testHarness(
  options: {
    configuredPath?: unknown;
    reviewExport?: unknown;
    reviewError?: Error;
    ignored?: boolean;
    initialTarget?: string;
  } = {},
) {
  const commands = new Map<string, (ctx: any) => unknown>();
  const events = new Map<string, (payload: any, ctx: any) => unknown>();
  const notifications: Array<{ message: string; type?: string }> = [];
  const reloads: string[][] = [];
  const writes: Array<{ path: string; snapshot: unknown }> = [];
  const executed: string[] = [];
  const repo = temporaryDirectory();
  const dependencies: WorkflowDependencies = {
    env: { HUNK_REVIEW_TARGET: options.initialTarget },
    pid: 4242,
    repoRoot: () => repo,
    isIgnored: () => options.ignored ?? true,
    runCommand: async (_command, args) => {
      reloads.push(args);
      if (args[1] === "list") {
        return {
          error: null,
          stdout: JSON.stringify({
            sessions: [
              { sessionId: "other-session", pid: 1111 },
              { sessionId: "current-session", pid: 4242 },
            ],
          }),
          stderr: "",
        };
      }
      if (args[1] === "review") {
        return options.reviewError
          ? { error: options.reviewError, stdout: "", stderr: options.reviewError.message }
          : {
              error: null,
              stdout: JSON.stringify(options.reviewExport ?? { review: { reviewNotes: [] } }),
              stderr: "",
            };
      }
      return { error: null, stdout: "", stderr: "" };
    },
    writeSnapshot: (path, value) => writes.push({ path, snapshot: value }),
  };
  const hunk = {
    config: { review_path: options.configuredPath },
    registerCommand: (definition: { id: string }, handler: (ctx: any) => unknown) => {
      commands.set(definition.id, handler);
    },
    on: (event: string, handler: (payload: any, ctx: any) => unknown) => {
      events.set(event, handler);
    },
  };
  createReviewWorkflowExtension(dependencies)(hunk as any);
  const context = {
    cwd: repo,
    notify: (message: string, type?: string) => notifications.push({ message, type }),
    commands: {
      execute: (command: string) => {
        executed.push(command);
        return true;
      },
    },
    dialogs: {
      select: async () => null,
      input: async () => null,
    },
  };
  return { commands, context, events, executed, notifications, reloads, repo, writes };
}

describe("review export", () => {
  test("automatically saves the live review when a note is saved", async () => {
    const review = snapshot([
      {
        id: "agent:1",
        source: "agent",
        fileKey: "file:README.md",
        anchor: { newRange: [2, 2], intersectingHunkIndices: [0], ownerHunkIndex: 0 },
        summary: "Agent comment",
        editable: false,
        resolution: "active",
      },
      {
        id: "user:1",
        source: "user",
        fileKey: "file:README.md",
        anchor: { newRange: [4, 4], intersectingHunkIndices: [0], ownerHunkIndex: 0 },
        summary: "Human comment",
        editable: true,
        resolution: "active",
      },
    ]);
    const exported = {
      review: {
        files: [{ path: "README.md" }],
        reviewNotes: [
          { noteId: "agent:1", source: "agent", filePath: "README.md", body: "Agent comment" },
          { noteId: "user:1", source: "user", filePath: "README.md", body: "Human comment" },
        ],
      },
    };
    const harness = testHarness({
      configuredPath: ".agents/reviews/current.json",
      reviewExport: exported,
    });

    await harness.events.get("note_changed")!(
      { kind: "created", note: review.notes[1] },
      harness.context,
    );

    expect(harness.writes).toEqual([
      {
        path: join(realpathSync(harness.repo), ".agents/reviews/current.json"),
        snapshot: exported,
      },
    ]);
    expect(harness.reloads).toEqual([
      ["session", "list", "--json"],
      ["session", "review", "current-session", "--include-notes", "--json"],
    ]);
    expect(harness.executed).toEqual([]);
    expect(harness.notifications.at(-1)?.message).toContain("Saved 2 review comments");
  });

  test("refuses an export that would become part of the Git review", async () => {
    const harness = testHarness({
      configuredPath: ".agents/reviews/current.json",
      ignored: false,
    });

    await harness.events.get("note_changed")!(
      { kind: "created", note: snapshot().notes[0] },
      harness.context,
    );

    expect(harness.writes).toEqual([]);
    expect(harness.notifications.at(-1)).toEqual({
      message:
        "Refusing to save review comments because .agents/reviews/current.json is not ignored by Git",
      type: "error",
    });
  });

  test("reports a live review export failure", async () => {
    const harness = testHarness({ reviewError: new Error("session unavailable") });

    await harness.events.get("note_changed")!(
      { kind: "created", note: snapshot().notes[0] },
      harness.context,
    );

    expect(harness.writes).toEqual([]);
    expect(harness.notifications.at(-1)).toEqual({
      message: "Failed to save review comments: session unavailable",
      type: "error",
    });
  });
});

describe("review path", () => {
  test("defaults to the ignored agent review directory", () => {
    const repo = temporaryDirectory();

    expect(resolveReviewPath(repo, undefined)).toBe(
      join(realpathSync(repo), ".agents/reviews/hunk-review.json"),
    );
  });

  test("rejects absolute paths and paths outside the review directory", () => {
    const repo = temporaryDirectory();

    expect(() => resolveReviewPath(repo, join(tmpdir(), "review.json"))).toThrow(
      "relative to the repository root",
    );
    expect(() => resolveReviewPath(repo, "../review.json")).toThrow("stay inside .agents/reviews");
    expect(() => resolveReviewPath(repo, ".env")).toThrow("stay inside .agents/reviews");
  });

  test("rejects a path that escapes through a symlink", () => {
    const repo = temporaryDirectory();
    const outside = temporaryDirectory();
    mkdirSync(join(repo, ".agents"));
    symlinkSync(outside, join(repo, ".agents", "reviews"));

    expect(() => resolveReviewPath(repo, ".agents/reviews/current.json")).toThrow(
      ".agents/reviews must stay inside the repository root",
    );
  });

  test("atomically replaces an earlier complete snapshot", () => {
    const repo = temporaryDirectory();
    const path = join(repo, "reviews", "current.json");
    mkdirSync(join(repo, "reviews"));
    writeFileSync(path, "old\n");
    const review = snapshot();

    writeReviewSnapshot(path, review);

    expect(JSON.parse(readFileSync(path, "utf8"))).toEqual(review);
    expect(existsSync(path)).toBe(true);
  });
});

describe("Review controls", () => {
  test("B toggles from working tree to main and back", async () => {
    const harness = testHarness({ initialTarget: "working" });

    await harness.commands.get("toggle-target")!(harness.context);
    await harness.commands.get("toggle-target")!(harness.context);

    expect(harness.reloads).toEqual([
      ["session", "list", "--json"],
      ["session", "reload", "current-session", "--", "diff", "main..."],
      ["session", "list", "--json"],
      ["session", "reload", "current-session", "--", "diff"],
    ]);
  });

  test("t toggles from stack to split and follows layout changes", () => {
    const harness = testHarness();

    harness.commands.get("toggle-layout")!(harness.context);
    harness.events.get("layout_changed")!({ mode: "auto", layout: "split" }, harness.context);
    harness.commands.get("toggle-layout")!(harness.context);

    expect(harness.executed).toEqual(["hunk.view.layoutSplit", "hunk.view.layoutStack"]);
  });
});
