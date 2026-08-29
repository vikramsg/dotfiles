import { readFile, stat } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

import { Plugin } from "@opencode-ai/plugin";
import { z } from "zod";

const MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024;

const SyncSourceSchema = z.object({
  id: z.string().min(1),
  local_dir: z.string().min(1),
  remote_dir: z.string().min(1),
  include: z.array(z.string().min(1)).min(1),
  exclude: z.array(z.string().min(1)).default([]),
});

const ScreenshotConfigSchema = z.object({
  sync: z.object({ sources: z.array(SyncSourceSchema) }),
});

const PluginOptionsSchema = z.object({
  screenshot_config: z.string().min(1).optional(),
  wait_ms: z.number().int().min(0).optional(),
  retry_ms: z.number().int().min(1).optional(),
});

type SyncSource = z.infer<typeof SyncSourceSchema>;
type PluginOptions = z.infer<typeof PluginOptionsSchema>;

export type SyncedAttachment = {
  path: string;
  uri: string;
  name: string;
};

function expandHome(value: string, home: string): string {
  if (value === "~") return home;
  if (value.startsWith("~/")) return path.join(home, value.slice(2));
  return value;
}

function matchesGlob(value: string, pattern: string): boolean {
  const expression = pattern
    .split("*")
    .map((part) => part.replace(/[|\\{}()[\]^$+?.]/g, "\\$&"))
    .join(".*");
  return new RegExp(`^${expression}$`).test(value);
}

function matchesSource(filename: string, source: SyncSource): boolean {
  return (
    source.include.some((pattern) => matchesGlob(filename, pattern)) &&
    !source.exclude.some((pattern) => matchesGlob(filename, pattern))
  );
}

function extractDroppedPath(text: string, source: SyncSource): { raw: string; path: string } | undefined {
  const roots = [source.local_dir, source.local_dir.replaceAll(" ", "\\ ")];
  for (const root of roots) {
    const start = text.indexOf(root);
    if (start < 0) continue;
    const candidate = text.slice(start).match(/^.*?\.png(?=\s|$)/)?.[0];
    if (!candidate) continue;
    const normalized = candidate.replace(/\\(.)/g, "$1");
    const relative = path.relative(source.local_dir, normalized);
    if (!relative || relative.startsWith("..") || path.dirname(relative) !== ".") {
      continue;
    }
    if (!matchesSource(path.basename(normalized), source)) continue;
    return { raw: candidate, path: normalized };
  }
}

async function readSources(configPath: string): Promise<SyncSource[]> {
  const config = ScreenshotConfigSchema.parse(JSON.parse(await readFile(configPath, "utf8")));
  return config.sync.sources;
}

async function waitForImage(filePath: string, waitMs: number, retryMs: number): Promise<boolean> {
  const deadline = Date.now() + waitMs;
  do {
    try {
      const info = await stat(filePath);
      if (info.isFile() && info.size > 0 && info.size <= MAX_ATTACHMENT_BYTES) return true;
    } catch {}
    if (Date.now() >= deadline) return false;
    await new Promise((resolve) => setTimeout(resolve, retryMs));
  } while (true);
}

export async function resolveSyncedAttachment(
  text: string,
  options: PluginOptions = {},
  home = os.homedir(),
): Promise<{ dropped: { raw: string; path: string }; attachment: SyncedAttachment } | undefined> {
  const configPath = expandHome(options.screenshot_config ?? "~/.config/screenshot/config.json", home);
  const sources = await readSources(configPath).catch(() => []);
  const waitMs = options.wait_ms ?? 2_000;
  const retryMs = options.retry_ms ?? 100;

  for (const source of sources) {
    const dropped = extractDroppedPath(text, source);
    if (!dropped) continue;
    const remotePath = path.join(expandHome(source.remote_dir, home), path.basename(dropped.path));
    if (!(await waitForImage(remotePath, waitMs, retryMs))) return;
    return {
      dropped,
      attachment: {
        path: remotePath,
        uri: pathToFileURL(remotePath).href,
        name: path.basename(remotePath),
      },
    };
  }
}

export default Plugin.define({
  id: "dotfiles.screenshot-sync-attachment-v2",

  async setup(ctx) {
    const options = PluginOptionsSchema.parse(ctx.options ?? {});
    const registration = await ctx.session.hook("prompt", async (event) => {
      const resolved = await resolveSyncedAttachment(event.prompt.text, options);
      if (!resolved) return;

      event.prompt.files ??= [];
      if (!event.prompt.files.some((file) => file.uri === resolved.attachment.uri)) {
        event.prompt.files.push({
          uri: resolved.attachment.uri,
          name: resolved.attachment.name,
        });
      }
      event.prompt.text = event.prompt.text.replace(resolved.dropped.raw, "[attached screenshot]");
    });

    return () => registration.dispose();
  },
});
