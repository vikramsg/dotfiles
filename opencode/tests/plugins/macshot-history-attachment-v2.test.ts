import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { describe, expect, it, vi } from "vitest";

import macshotHistoryAttachment, {
  resolveSyncedAttachment,
} from "../../plugins/macshot-history-attachment-v2.ts";

const MACSHOT_HISTORY = "/Users/vikramsingh/Library/Containers/com.sw33tlie.macshot.macshot/Data/Library/Application Support/com.sw33tlie.macshot/history";

async function config(root: string, remoteDir: string) {
  const file = path.join(root, "screenshot.json");
  await writeFile(
    file,
    JSON.stringify({
      sync: {
        sources: [
          {
            id: "macshot-history",
            local_dir: MACSHOT_HISTORY,
            vm_host: "vm-us",
            remote_dir: remoteDir,
            include: ["*.png"],
            exclude: ["*_preview.png", "*_thumb.png", "*_raw.png"],
          },
        ],
      },
    }),
  );
  return file;
}

function dropped(filename: string) {
  return `${MACSHOT_HISTORY}/${filename}`;
}

describe("macshot history attachment V2 plugin", () => {
  it("exports the expected V2 plugin definition", () => {
    expect(macshotHistoryAttachment.id).toBe("dotfiles.macshot-history-attachment-v2");
    expect(macshotHistoryAttachment.setup).toBeTypeOf("function");
  });

  it("maps an escaped dropped history path to the synced VM image", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "macshot-plugin-"));
    const remoteDir = path.join(root, "remote");
    const filename = "8E296E20-4BB1-4C02-80BD-CDF1BDFFD727.png";
    await mkdir(remoteDir, { recursive: true });
    await writeFile(path.join(remoteDir, filename), "png");
    const screenshotConfig = await config(root, remoteDir);
    const text = dropped(filename).replace("Application Support", "Application\\ Support");

    const resolved = await resolveSyncedAttachment(text, { screenshot_config: screenshotConfig, wait_ms: 0 });

    expect(resolved?.dropped.path).toBe(dropped(filename));
    expect(resolved?.attachment.name).toBe(filename);
    expect(resolved?.attachment.uri).toBe(`file://${path.join(remoteDir, filename)}`);
  });

  it.each(["capture_preview.png", "capture_thumb.png", "capture_raw.png", "capture.json"]) (
    "ignores unsupported history file %s",
    async (filename) => {
      const root = await mkdtemp(path.join(os.tmpdir(), "macshot-plugin-"));
      const screenshotConfig = await config(root, path.join(root, "remote"));

      const resolved = await resolveSyncedAttachment(dropped(filename), {
        screenshot_config: screenshotConfig,
        wait_ms: 0,
      });

      expect(resolved).toBeUndefined();
    },
  );

  it("does not attach when rsync has not delivered the remote image", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "macshot-plugin-"));
    const screenshotConfig = await config(root, path.join(root, "remote"));

    const resolved = await resolveSyncedAttachment(dropped("capture.png"), {
      screenshot_config: screenshotConfig,
      wait_ms: 0,
    });

    expect(resolved).toBeUndefined();
  });

  it("adds the remote image attachment through the prompt hook", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "macshot-plugin-"));
    const remoteDir = path.join(root, "remote");
    const filename = "capture.png";
    await mkdir(remoteDir, { recursive: true });
    await writeFile(path.join(remoteDir, filename), "png");
    const screenshotConfig = await config(root, remoteDir);
    let handler: ((event: any) => Promise<void>) | undefined;
    const dispose = vi.fn(async () => undefined);
    const hook = vi.fn(async (name: string, callback: (event: any) => Promise<void>) => {
      expect(name).toBe("prompt");
      handler = callback;
      return { dispose };
    });

    const cleanup = await macshotHistoryAttachment.setup({
      options: { screenshot_config: screenshotConfig, wait_ms: 0 },
      session: { hook },
    } as never);
    const event: {
      prompt: { text: string; files?: Array<{ uri: string; name: string; mime: string }> };
    } = { prompt: { text: `Please inspect ${dropped(filename)}` } };

    await handler?.(event);

    expect(event.prompt.text).toBe("Please inspect [attached screenshot]");
    expect(event.prompt.files).toEqual([
      {
        uri: `file://${path.join(remoteDir, filename)}`,
        name: filename,
      },
    ]);
    await cleanup?.();
    expect(dispose).toHaveBeenCalledOnce();
  });
});
