// A full-height sidebar for terminal apps: the layout's `app-sidebar` block,
// beside the panes, showing one terminal at a time. Each tab has its own
// instance of each app in apps.js, found by its labels and started on the
// tab's machine in its focused pane's folder. Hiding the block leaves the app
// running, state and all.
//
// Roles, by props:
// - {role: "sync"}: a floating block that draws nothing. It takes
//   `app-sidebar.toggle:<app>` key commands, and when the shown tab changes it
//   shows that tab's app, or hides the block if the tab has none open.
// - none: the block itself before any app is put in it; draws nothing.
//
// gitview's Enter opens files in an nvim a layout block shows (this computer
// only), so it uses the sidebar's nvim while it shows.

import { View, div } from "gpui-kit";
import { checking, focused, hc, layout, nextCommand, notify, panes, props, run, spaces, terminals } from "herdr";
import { APPS } from "./apps.js";

const ID = "app-sidebar";
const TAB = "app-sidebar.tab";
const APP = "app-sidebar.app";

function find(node, id) {
  if (node?.id === id) return node;
  for (const c of node?.children ?? []) {
    const hit = find(c, id);
    if (hit) return hit;
  }
  return null;
}

// The block, right of the tab's panes, for a layout that lost it or never had
// it (`just herdr-app` adds it to main-copy). Returns it, added to `tree`.
function addBlock(tree) {
  const block = { id: ID, type: "block", size: { weight: 0.6667 }, min: 320, radius: 6, border: { width: 1, color: "border" } };
  const row = (function parentOf(node) {
    if (node.children?.some((c) => c.content?.tab === "active")) return node;
    for (const c of node.children ?? []) {
      const hit = parentOf(c);
      if (hit) return hit;
    }
    return null;
  })(tree);
  if (!row || row.type !== "row") throw new Error("This layout has no row beside its tab's panes for the sidebar.");
  const at = row.children.findIndex((c) => c.content?.tab === "active");
  row.children.splice(at + 1, 0, block);
  return block;
}

const machineOf = (address) => (address.includes("/") ? address.split("/")[0] : null);
const live = (address) => terminals().some((t) => t.address === address && t.state === "live");
const instance = (tab, app) => terminals().find((t) => t.state === "live" && t.labels?.[TAB] === tab && t.labels?.[APP] === app);

export default class AppSidebar extends View {
  init(_props, cx) {
    if (checking() || props()?.role !== "sync") return;
    this.open = new Map(); // tab -> the app its sidebar shows
    this.last = new Map(); // tab -> its pane focused last, for leaving the sidebar
    this.tab = focused()?.tab ?? null;
    this.busy = false;
    cx.spawn(async (cx) => {
      for (;;) {
        const [verb, arg] = (await nextCommand()).split(":");
        if (verb === "toggle") await this.guard(() => this.toggle(arg, cx));
        else if (verb === "go") await this.guard(() => this.go(arg, cx));
      }
    });
    cx.timer.every(250, () => {
      const f = focused();
      const tab = f?.tab ?? null;
      if (f?.pane) this.last.set(tab, f.pane);
      if (this.busy) return;
      const node = find(layout(), ID);
      const shown = node && !node.hidden ? node.content?.terminal : null;
      // A tab switch, or the shown app quit.
      if (tab !== this.tab || (shown && !live(shown))) {
        this.tab = tab;
        this.guard(async () => this.follow());
      }
    });
  }

  async guard(action) {
    this.busy = true;
    try {
      await action();
    } catch (e) {
      notify({ title: "Sidebar", body: String(e?.message ?? e), level: "error" });
    } finally {
      this.busy = false;
    }
  }

  follow() {
    const node = find(layout(), ID);
    if (!node) return;
    const app = this.open.get(this.tab);
    const mine = app ? instance(this.tab, app) : null;
    if (mine) this.show(mine.address, false);
    else {
      this.open.delete(this.tab);
      if (!node.hidden) run("layout.hide", { id: ID });
    }
  }

  // Pane navigation that knows the sidebar: right from the rightmost pane goes
  // into it, left from it goes back to the tab's last pane. The app's pane.go
  // sees only panes, and fails while a layout block has the keyboard.
  async go(direction, cx) {
    const f = focused();
    if (!f?.tab) return;
    if (!f.pane) {
      const pane = this.last.get(f.tab) ?? panes().filter((p) => p.tab === f.tab).at(-1)?.pane;
      if (direction === "left" && pane) run("pane.focus", { pane });
      return;
    }
    run("pane.go", { direction });
    if (direction !== "right") return;
    await cx.sleep(150);
    const node = find(layout(), ID);
    const shown = node && !node.hidden ? node.content?.terminal : null;
    if (shown && focused()?.pane === f.pane) run("pane.focus", { terminal: shown });
  }

  async toggle(app, cx) {
    if (!APPS[app]) throw new Error(`No app "${app}" in app-sidebar/apps.js.`);
    const f = focused();
    if (!f?.tab) throw new Error("Open a tab first.");
    const node = find(layout(), ID);
    this.tab = f.tab;
    const mine = instance(f.tab, app);
    if (mine && node && !node.hidden && node.content?.terminal === mine.address) {
      this.open.delete(f.tab);
      run("layout.hide", { id: ID });
      return;
    }
    const machine = spaces().find((s) => s.id === f.space)?.machine ?? null;
    await this.sweep(machine);
    const address = mine?.address ?? (await this.start(f, app, machine));
    // The block can only show a terminal the app has listed, a moment after `hc run`.
    for (let i = 0; i < 50 && !terminals().some((t) => t.address === address); i++) await cx.sleep(100);
    this.open.set(f.tab, app);
    this.show(address, true);
  }

  show(address, focus) {
    const root = layout();
    const node = find(root, ID);
    if (node?.content?.terminal !== address) {
      // The new tree carries the block shown: the set keeps a `hidden` it is given.
      const tree = JSON.parse(JSON.stringify(root));
      const block = find(tree, ID) ?? addBlock(tree);
      block.content = { terminal: address };
      delete block.hidden;
      run("layout.set", { layout: tree });
    }
    run("layout.show", { id: ID });
    if (focus) run("pane.focus", { terminal: address });
  }

  // Ends the apps of closed tabs on one machine, whose tabs are known here.
  async sweep(machine) {
    const tabs = new Set(spaces().flatMap((s) => s.tabs.map((t) => t.id)));
    for (const t of terminals()) {
      const tab = t.state === "live" ? t.labels?.[TAB] : null;
      if (tab && !tabs.has(tab) && machineOf(t.address) === machine) await hc(["kill", t.address]);
    }
  }

  async start(f, app, machine) {
    const args = ["run", "--json", "--bg", "--no-parent", "--label", `${TAB}=${f.tab}`, "--label", `${APP}=${app}`];
    if (f.cwd) args.push("--cwd", f.cwd);
    if (machine) args.push("--on", machine);
    args.push("--", "zsh", "-lc", APPS[app]);
    const r = await hc(args);
    if (r.code !== 0) throw new Error(r.stderr.trim() || `hc run exited ${r.code}`);
    return JSON.parse(r.stdout).address;
  }

  render() {
    return div();
  }
}
