import { execFile } from "node:child_process";

function getHunkBin(): string {
  if (process.env.HUNK_BIN_PATH) return process.env.HUNK_BIN_PATH;
  const standardPaths = [
    "/home/linuxbrew/.linuxbrew/bin/hunk",
    "/opt/homebrew/bin/hunk",
    "/usr/local/bin/hunk",
  ];
  for (const p of standardPaths) {
    try {
      if (require("node:fs").existsSync(p)) return p;
    } catch {}
  }
  return "hunk";
}

export default function (hunk: any) {
  hunk.registerCommand(
    {
      id: "switch-target",
      title: "Switch Review Target...",
      key: "ctrl+b",
    },
    async (ctx: any) => {
      const options = [
        "Uncommitted changes (working tree)",
        "Branch diff vs main (main...)",
        "Branch diff vs origin/main (origin/main...)",
        "Staged changes only (--staged)",
        "Last commit (HEAD~1)",
        "Custom revision / range...",
      ];

      const picked = await ctx.dialogs.select({
        title: "Switch Review Target",
        options,
      });

      if (!picked) return;

      let reloadArgs: string[] = [];

      if (picked.startsWith("Uncommitted")) {
        reloadArgs = ["diff"];
      } else if (picked.startsWith("Branch diff vs main")) {
        reloadArgs = ["diff", "main..."];
      } else if (picked.startsWith("Branch diff vs origin/main")) {
        reloadArgs = ["diff", "origin/main..."];
      } else if (picked.startsWith("Staged")) {
        reloadArgs = ["diff", "--staged"];
      } else if (picked.startsWith("Last commit")) {
        reloadArgs = ["show", "HEAD~1"];
      } else if (picked.startsWith("Custom")) {
        const input = await ctx.dialogs.input({
          title: "Custom Revision / Range",
          placeholder: "e.g. main...HEAD, HEAD~2, or v1.0.0...",
        });
        if (!input || !input.trim()) return;
        const trimmed = input.trim();
        if (trimmed.startsWith("show ") || trimmed.startsWith("diff ")) {
          reloadArgs = trimmed.split(/\s+/);
        } else {
          reloadArgs = ["diff", ...trimmed.split(/\s+/)];
        }
      }

      if (reloadArgs.length === 0) return;

      const repoPath = ctx.cwd || process.cwd();
      const hunkBin = getHunkBin();

      execFile(hunkBin, ["session", "reload", "--repo", repoPath, "--", ...reloadArgs], (err, stdout, stderr) => {
        if (err) {
          ctx.notify(`Failed to reload target: ${stderr || err.message}`, "error");
        } else {
          ctx.notify(`Switched to: hunk ${reloadArgs.join(" ")}`);
        }
      });
    }
  );
}
