// The tab's nvim in a pane on the right of the focused pane, toggled by
// `mod.open:nvim-sidebar`. Hiding parks the terminal instead of ending it, so
// buffers and cursor survive until the next show. One nvim per tab, found by
// its `nvim-sidebar.tab` label; ones whose tab is gone are killed on the next
// toggle. While shown, gitview's Enter opens files in it (an nvim running in
// the tab). This copy acts, then closes itself.

import { View, div } from "gpui-kit";
import { checking, closeOverlay, focused, hc, notify, panes, props, run, spaces, terminals } from "herdr";

const LABEL = "nvim-sidebar.tab";

export default class NvimSidebar extends View {
  init(_props, cx) {
    if (checking()) return;
    cx.spawn(async (cx) => {
      try {
        await this.toggle(cx);
      } catch (e) {
        notify({ title: "nvim sidebar", body: String(e?.message ?? e), level: "error" });
      } finally {
        closeOverlay(props()?.overlay);
      }
    });
  }

  async toggle(cx) {
    const f = focused();
    if (!f?.tab || !f.pane) throw new Error("Focus a pane in a tab first.");
    const tabs = new Set(spaces().flatMap((s) => s.tabs.map((t) => t.id)));
    const ours = terminals().filter((t) => t.state === "live" && t.labels?.[LABEL]);
    for (const t of ours) if (!tabs.has(t.labels[LABEL])) await hc(["kill", t.address]);

    const mine = ours.find((t) => t.labels[LABEL] === f.tab);
    if (mine && panes().some((p) => p.terminal === mine.address)) {
      run("terminal.park", { terminal: mine.address });
      return;
    }
    const address = mine?.address ?? (await this.start(f));
    // The app's terminal list lags `hc run`; keep refuses a terminal it hasn't listed.
    for (let i = 0; i < 30 && !terminals().some((t) => t.address === address); i++) await cx.sleep(100);
    run("terminal.keep", { terminal: address, place: "right" });
    // The keep lands a moment later; then the keyboard goes to nvim.
    for (let i = 0; i < 30; i++) {
      if (panes().some((p) => p.terminal === address)) return run("pane.focus", { terminal: address });
      await cx.sleep(100);
    }
  }

  async start(f) {
    const machine = spaces().find((s) => s.id === f.space)?.machine ?? null;
    const args = ["run", "--json", "--bg", "--no-parent", "--label", `${LABEL}=${f.tab}`];
    if (f.cwd) args.push("--cwd", f.cwd);
    if (machine) args.push("--on", machine);
    // The core's PATH may lack Homebrew and mise; zsh loads ~/.zshenv first.
    args.push("--", "/bin/zsh", "-c", "exec nvim");
    const r = await hc(args);
    if (r.code !== 0) throw new Error(r.stderr.trim() || `hc run exited ${r.code}`);
    return JSON.parse(r.stdout).address;
  }

  render() {
    return div();
  }
}
