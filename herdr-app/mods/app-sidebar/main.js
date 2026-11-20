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
// only), so it uses the sidebar's nvim while it shows. `app-sidebar.open:<path>`
// (filetree's Enter) opens a file in the tab's sidebar nvim, through the socket
// each app is given as $APP_SIDEBAR_SOCK, on the tab's machine.

import { View, div } from "gpui-kit";
import { checking, exec, focused, hc, layout, nextCommand, notify, panes, props, run, spaces, terminals } from "herdr";
import { APPS } from "./apps.js";

const ID = "app-sidebar";
const TAB = "app-sidebar.tab";
const APP = "app-sidebar.app";
// The sidebar's weight against the tab's panes at 1: 40% of the row they share.
// The app rewrites both weights when blocks beside them are shown or hidden, so
// showing the sidebar sets both again.
const WEIGHT = 0.6667;

function find(node, id) {
  if (node?.id === id) return node;
  for (const c of node?.children ?? []) {
    const hit = find(c, id);
    if (hit) return hit;
  }
  return null;
}

// The layout block that shows the focused tab's panes.
function findPanes(node) {
  if (node?.content?.tab === "active") return node;
  for (const c of node?.children ?? []) {
    const hit = findPanes(c);
    if (hit) return hit;
  }
  return null;
}

// The block, right of the tab's panes, for a layout that lost it or never had
// it (`just herdr-app` adds it to main-copy). Returns it, added to `tree`.
function addBlock(tree) {
  const block = { id: ID, type: "block", size: { weight: WEIGHT }, min: 320, radius: 6, border: { width: 1, color: "border" } };
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

// Run in the sidebar's nvim with the path as _A: picks a window holding a file
// (not the explorer's, a nofile buffer) and opens the path there.
const OPEN_LUA = [
  "(function(p)",
  "for _, w in ipairs(vim.api.nvim_tabpage_list_wins(0)) do",
  "local b = vim.api.nvim_win_get_buf(w)",
  'if vim.bo[b].buftype == "" and vim.api.nvim_win_get_config(w).relative == "" then vim.api.nvim_set_current_win(w) break end',
  "end",
  "vim.cmd.drop(vim.fn.fnameescape(p))",
  "return 1",
  "end)(_A)",
].join(" ");

const machineOf = (address) => (address.includes("/") ? address.split("/")[0] : null);
const live = (address) => terminals().some((t) => t.address === address && t.state === "live");
// Per tab: the tab's id is in the socket's name, so a restarted nvim takes it over.
const socketOf = (tab) => `/tmp/herdr-app-sidebar-${tab.replace(/[^A-Za-z0-9]/g, "_")}.sock`;
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
        const [verb, ...rest] = (await nextCommand()).split(":");
        const arg = rest.join(":");
        if (verb === "toggle") await this.guard(() => this.toggle(arg, cx));
        else if (verb === "go") await this.guard(() => this.go(arg, cx));
        else if (verb === "open") await this.guard(() => this.openFile(arg, cx));
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

  // Opens `path` in the tab's sidebar nvim, showing it (and starting it) first, in
  // its editor window rather than the explorer's, and focuses it.
  async openFile(path, cx) {
    const f = focused();
    if (!f?.tab) throw new Error("Open a tab first.");
    const machine = spaces().find((s) => s.id === f.space)?.machine ?? null;
    const node = find(layout(), ID);
    const before = instance(f.tab, "nvim");
    if (!before || !node || node.hidden || node.content?.terminal !== before.address) await this.toggle("nvim", cx);
    const mine = instance(f.tab, "nvim");
    if (!mine) throw new Error("The sidebar's nvim did not start.");
    const expr = `luaeval('${OPEN_LUA.replaceAll("'", "''")}', '${path.replaceAll("'", "''")}')`;
    // A new nvim takes a moment to listen.
    let r;
    for (let i = 0; i < 30; i++) {
      r = await exec("zsh", ["-lc", 'exec nvim --server "$1" --remote-expr "$2"', "zsh", socketOf(f.tab), expr], { on: machine });
      if (r.code === 0 || before) break;
      await cx.sleep(200);
    }
    if (r.code !== 0) throw new Error(before ? "This tab's nvim was started before it could take files; quit it and open it again." : r.stderr.trim() || "nvim did not take the file.");
    this.show(mine.address, true);
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
    const panes = findPanes(layout());
    if (panes?.id) run("layout.resize", { id: panes.id, weight: 1 });
    run("layout.resize", { id: ID, weight: WEIGHT });
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
    const sock = socketOf(f.tab);
    args.push("--", "zsh", "-lc", `export APP_SIDEBAR_SOCK='${sock}'; ${APPS[app]}`);
    const r = await hc(args);
    if (r.code !== 0) throw new Error(r.stderr.trim() || `hc run exited ${r.code}`);
    return JSON.parse(r.stdout).address;
  }

  render() {
    return div();
  }
}
