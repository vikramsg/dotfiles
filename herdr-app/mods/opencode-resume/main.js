// Runs `opencode-resume resume` on this computer and on every connected machine, then shows
// what came back in a toast. After a reboot or a lost herdr-core, terminals come back as plain
// shells; each machine's lch service (`opencode-resume watch`) saved which OpenCode session each
// one had open. Opened with `mod.open:opencode-resume`; this copy acts, then closes itself.

import { View, div } from "gpui-kit";
import { checking, closeOverlay, exec, machines, notify, props } from "herdr";

async function resumeOn(machine) {
  const where = machine ?? "this computer";
  const r = await exec("zsh", ["-lc", "opencode-resume resume --json"], { on: machine }).catch((e) => ({ code: -1, stderr: String(e?.message ?? e) }));
  const failed = (why) => ({ resumed: 0, ok: false, lines: [`${where}: ${why}`] });
  if (r.code !== 0) return failed((r.stderr || `exit ${r.code}`).trim());
  let outcomes;
  try {
    // The last line: a login shell can print to stdout before the command runs.
    outcomes = JSON.parse(r.stdout.trim().split("\n").at(-1) || "[]");
  } catch {
    return failed(`unexpected output: ${r.stdout.trim().slice(0, 200)}`);
  }
  const address = (o) => (machine ? `${machine}/${o.address}` : o.address);
  return {
    resumed: outcomes.filter((o) => o.command).length,
    ok: outcomes.every((o) => o.command),
    lines: outcomes.map((o) => `${address(o)} ${o.folder}: ${o.reason ?? "resumed"}`),
  };
}

export default class OpencodeResume extends View {
  init(_props, cx) {
    if (checking()) return;
    const overlay = props()?.overlay;
    cx.spawn(async () => {
      try {
        const names = [null, ...new Set(machines().map((m) => m.name).filter(Boolean))];
        const results = await Promise.all(names.map(resumeOn));
        const resumed = results.reduce((n, r) => n + r.resumed, 0);
        const lines = results.flatMap((r) => r.lines);
        notify({
          title: resumed ? `Resumed ${resumed} OpenCode session${resumed === 1 ? "" : "s"}` : "No OpenCode sessions resumed",
          body: lines.join("\n") || "Nothing was waiting to resume.",
          level: results.every((r) => r.ok) ? "success" : "warning",
        });
      } finally {
        closeOverlay(overlay);
      }
    });
  }

  render() {
    return div();
  }
}
