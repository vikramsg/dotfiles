import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { writeSync } = vi.hoisted(() => ({ writeSync: vi.fn() }));

vi.mock("node:fs", () => ({ writeSync }));

import zedBell, { ring } from "../../plugins/tui/zed-bell-v2.ts";

type Handler = (event: unknown) => void;

function harness() {
  const handlers = new Map<string, Set<Handler>>();
  const unsubscribes: ReturnType<typeof vi.fn>[] = [];
  const on = vi.fn((type: string, handler: Handler) => {
    const entries = handlers.get(type) ?? new Set<Handler>();
    entries.add(handler);
    handlers.set(type, entries);
    const off = vi.fn(() => entries.delete(handler));
    unsubscribes.push(off);
    return off;
  });
  const emit = (type: string) => {
    for (const handler of handlers.get(type) ?? []) handler({ type });
  };

  return {
    context: { data: { on } } as never,
    emit,
    handlers,
    on,
    unsubscribes,
  };
}

describe("Zed bell V2 TUI plugin", () => {
  beforeEach(() => {
    writeSync.mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("exports the expected V2 TUI plugin definition", () => {
    expect(zedBell.id).toBe("dotfiles.zed-bell-v2");
    expect(zedBell.setup).toBeTypeOf("function");
  });

  it("writes one BEL byte", () => {
    ring();

    expect(writeSync).toHaveBeenCalledOnce();
    expect(writeSync).toHaveBeenCalledWith(process.stdout.fd, "\x07");
  });

  it("subscribes only to terminal execution and permission events", async () => {
    const test = harness();

    await zedBell.setup(test.context);

    expect(test.on.mock.calls.map(([type]) => type)).toEqual([
      "session.execution.succeeded",
      "session.execution.failed",
      "session.execution.interrupted",
      "permission.asked",
    ]);
  });

  it("rings once for each matching event and ignores unrelated events", async () => {
    const test = harness();
    await zedBell.setup(test.context);

    test.emit("session.status");
    test.emit("permission.replied");
    test.emit("session.execution.succeeded");
    test.emit("session.execution.failed");
    test.emit("session.execution.interrupted");
    test.emit("permission.asked");

    expect(writeSync).toHaveBeenCalledTimes(4);
    expect(writeSync).toHaveBeenNthCalledWith(1, process.stdout.fd, "\x07");
    expect(writeSync).toHaveBeenNthCalledWith(2, process.stdout.fd, "\x07");
    expect(writeSync).toHaveBeenNthCalledWith(3, process.stdout.fd, "\x07");
    expect(writeSync).toHaveBeenNthCalledWith(4, process.stdout.fd, "\x07");
  });

  it("unregisters both handlers during cleanup", async () => {
    const test = harness();
    const cleanup = await zedBell.setup(test.context);
    if (!cleanup) throw new Error("Cleanup was not returned");

    await cleanup();
    test.emit("session.execution.succeeded");
    test.emit("session.execution.failed");
    test.emit("session.execution.interrupted");
    test.emit("permission.asked");

    expect(test.unsubscribes).toHaveLength(4);
    expect(test.unsubscribes[0]).toHaveBeenCalledOnce();
    expect(test.unsubscribes[1]).toHaveBeenCalledOnce();
    expect(test.unsubscribes[2]).toHaveBeenCalledOnce();
    expect(test.unsubscribes[3]).toHaveBeenCalledOnce();
    expect(writeSync).not.toHaveBeenCalled();
  });

  it("does not accumulate handlers after cleanup and reload", async () => {
    const test = harness();
    const firstCleanup = await zedBell.setup(test.context);
    if (!firstCleanup) throw new Error("Cleanup was not returned");
    await firstCleanup();

    await zedBell.setup(test.context);
    test.emit("session.execution.succeeded");

    expect(writeSync).toHaveBeenCalledOnce();
  });
});
