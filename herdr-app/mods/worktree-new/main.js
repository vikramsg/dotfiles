// New worktree dialog on prefix+n (`mod.open:worktree-new`), for the focused
// space, in the focused pane's folder. New branches start from a freshly
// fetched origin/<default branch>, not from whatever the focused checkout has
// checked out. A trimmed copy of Herdr's shipped `worktree` mod (new only);
// herdr-app/README.md lists what was copied, changed and dropped.
// Opened with props, { space, folder } replace the focused ones and { branch }
// makes it at once, as the shipped one does.

import { View, div } from "gpui-kit";
import { v_flex, h_flex, InputState, Input } from "gpui-base";
import { run, props, closeOverlay, theme, spaces, panes, focused, exec, home, appHome, readTextFile } from "herdr";

// Where a space is now: its first terminal's live folder, else where it was made.
function place(s, all = panes()) {
  if (!s) return null;
  const tabs = new Set((s.tabs ?? []).map((c) => c.id));
  return all.find((p) => tabs.has(p.tab) && p.cwd)?.cwd || s.folder || null;
}

// The shipped dialog's checkout folder: settings.json worktrees.directory, on the space's machine.
async function root(userHome) {
  const raw = await readTextFile(`${appHome()}/settings.json`);
  const directory = (raw === null ? {} : JSON.parse(raw))?.worktrees?.directory ?? "~/.herdr/worktrees";
  if (typeof directory !== "string" || !directory.trim()) throw new Error("worktrees.directory must be a non-empty path.");
  let path = directory;
  if (path === "~" || path.startsWith("~/")) path = userHome.replace(/\/$/, "") + path.slice(1);
  if (!path.startsWith("/")) throw new Error("worktrees.directory must be an absolute path or start with ~/.");
  return path.replace(/\/+$/, "");
}
const tilde = (path, userHome) => (path.startsWith(userHome) ? `~${path.slice(userHome.length)}` : path);
// The shipped dialog's folder name for a branch, so both put a branch in the same place.
const slug = (branch) => {
  const normalized = branch.normalize("NFC");
  const name = normalized.replace(/[^\p{L}\p{M}\p{N}._-]+/gu, "-").replace(/^-+|-+$/g, "");
  if (name) return name;
  let hash = 2166136261;
  for (const char of normalized) hash = Math.imul(hash ^ char.codePointAt(0), 16777619);
  return `branch-${(hash >>> 0).toString(16).padStart(8, "0")}`;
};

async function git(cwd, args, on, timeout) {
  const r = await exec("git", args, { cwd, on, ...(timeout === undefined ? {} : { timeout }) });
  return { ok: r.code === 0, out: (r.stdout ?? "").trim(), err: (r.stderr ?? r.stdout ?? "").trim() };
}

// The repo a folder belongs to: its main checkout and name. null outside git.
async function repoOf(folder, on) {
  const common = await git(folder, ["rev-parse", "--path-format=absolute", "--git-common-dir"], on);
  if (!common.ok) return null;
  const main = common.out.endsWith("/.git") ? common.out.slice(0, -5) : common.out;
  return { main, name: main.split("/").pop() };
}

// origin's default branch (origin/HEAD, else main), fetched now: origin/<branch>
// only moves on a fetch, so without one a new branch could start from a stale commit.
// The refspec names the destination, so a single-branch clone of another branch
// updates origin/<branch> too. `oid` is what the dialog shows and what new branches start from.
async function base(repo, on) {
  const head = await git(repo.main, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], on);
  const branch = head.ok ? head.out.replace(/^origin\//, "") : "main";
  const ref = `refs/remotes/origin/${branch}`;
  const fetched = await git(repo.main, ["fetch", "--quiet", "origin", `+refs/heads/${branch}:${ref}`], on, 120_000);
  if (!fetched.ok) throw new Error(`Couldn't fetch origin ${branch}: ${fetched.err || "git fetch failed."}`);
  const commit = await git(repo.main, ["log", "-1", "--format=%H%x09%h %s", ref], on);
  if (!commit.ok) throw new Error(commit.err || `origin/${branch} not found.`);
  const [oid, label] = commit.out.split("\t");
  return { name: `origin/${branch}`, oid, label };
}

export default class WorktreeNew extends View {
  init(_props, cx) {
    // Read once: the focus can move while the dialog is open.
    const f = focused();
    this.spaceId = props()?.space ?? f?.space;
    this.startFolder = props()?.folder ?? panes().find((p) => p.focused)?.cwd ?? f?.cwd ?? undefined;
    this.on = this.space()?.machine;
    this.userHome = this.on ? null : home();
    this.text = props()?.branch ?? "";
    this.input = InputState.new({ value: this.text, placeholder: "branch name" });
    this.input.on("change", (_e, cx) => { this.text = this.input.value(); this.error = ""; cx.notify(); });
    this.input.on("submit", (_e, cx) => this.go(cx));
    this.inputFocused = true;
    this.input.on("focus", (_e, cx) => { this.inputFocused = true; cx.notify(); });
    this.input.on("blur", (_e, cx) => { this.inputFocused = false; cx.notify(); });
    this.handle = cx.focus_handle();
    this.handle.focus();
    this.input.focus();
    this.busy = false;
    this.error = ""; // the last Enter's failure; typing clears it
    this.failed = ""; // loading's failure; it stays, and Enter stays off
    this.repo = undefined; // undefined: looking, null: not in git
    this.base = undefined; // { name, oid, label } once fetched
    if (!this.space()) {
      this.repo = null;
      this.failed = "Open a space first.";
      return;
    }
    cx.spawn(async (cx) => {
      try {
        if (this.on) {
          const result = await exec("sh", ["-c", 'printf %s "$HOME"'], { on: this.on });
          if (result.code !== 0 || !result.stdout.trim()) throw new Error("Could not find the remote home folder.");
          this.userHome = result.stdout.trim();
        }
        this.root = await root(this.userHome);
        this.folder = this.startFolder || place(this.space()) || this.userHome;
        this.repo = await repoOf(this.folder, this.on);
        cx.notify();
        if (this.repo) this.base = await base(this.repo, this.on);
      } catch (error) { this.failed = String(error); }
      cx.notify();
      cx.timer.after(100, () => this.input.focus());
      if (props()?.branch) this.go(cx);
    });
  }

  space() {
    return spaces().find((s) => s.id === this.spaceId);
  }

  close() {
    closeOverlay(props().overlay);
  }

  go(cx) {
    if (this.busy || !this.repo || !this.base) return;
    cx.spawn(async (cx) => {
      this.busy = true;
      this.error = "";
      cx.notify();
      try { this.error = await this.create(); } catch (error) { this.error = String(error); }
      this.busy = false;
      if (!this.error) this.close();
      cx.notify();
    });
  }

  async create() {
    const branch = this.text.trim();
    if (!branch) return "Type a branch name.";
    const path = `${this.root}/${this.repo.name}/${slug(branch)}`;
    const exists = (await git(this.repo.main, ["show-ref", "--verify", "--quiet", `refs/heads/${branch}`], this.on)).ok;
    // --no-track: a branch made from origin/main would otherwise have main as its upstream.
    const add = exists ? ["worktree", "add", path, branch] : ["worktree", "add", "--no-track", "-b", branch, path, this.base.oid];
    const r = await git(this.repo.main, add, this.on, 600_000);
    if (!r.ok) return r.err || "git worktree add failed.";
    // Leave spaces unnamed so they follow the checkout folder and nest under the repo.
    run("space.new", { folder: path, machine: this.on ?? "" });
    return "";
  }

  key(e) {
    if (e.key === "escape") this.close();
  }

  render() {
    const t = theme();
    const r = this.repo;
    const b = this.base;
    const title = `New worktree${r ? ` of ${r.name}` : ""}`;
    const detail =
      r === undefined
        ? "…"
        : r === null
          ? this.folder ? `${tilde(this.folder, this.userHome)} is not in a git repository.` : ""
          : `A new space on a checkout in ${tilde(this.root, this.userHome)}/${r.name}/. A branch that exists is checked out as it is.`;
    const from = r && !b && !this.failed ? "Fetching origin…" : b ? `New branches start from ${b.name}: ${b.label}` : "";
    const ready = Boolean(r && b);
    return v_flex()
      .id("worktree-new")
      .track_focus(this.handle)
      .on_key_down((e) => this.key(e))
      .size_full()
      .p(16)
      .gap(10)
      .bg(t.popover)
      .text_size(13)
      .child(div().font_semibold().text_color(t.foreground).child(title))
      .when(Boolean(detail), (el) => el.child(div().text_color(t.muted).child(detail)))
      .when(Boolean(from), (el) => el.child(div().truncate().text_color(b ? t.foreground : t.muted).child(from)))
      .when(Boolean(r), (el) =>
        el.child(
          Input.new(this.input)
            .h(32)
            .px(10)
            .items_center()
            .rounded(6)
            .border(1)
            .border_color(this.inputFocused ? t.accent : t.input)
            .bg(t.background)
            .text_color(t.foreground),
        ),
      )
      .when(Boolean(this.failed || this.error), (el) => el.child(div().text_color(t.blocked).child(this.failed || this.error)))
      .child(div().flex_1())
      .child(
        h_flex()
          .justify_end()
          .text_size(11)
          .text_color(t.dim)
          .gap(6)
          .when(this.busy, (el) => el.child(div().frames(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"], 90)))
          .child(this.busy ? "working…" : ready ? "↵ create · esc cancel" : "esc close"),
      );
  }
}
