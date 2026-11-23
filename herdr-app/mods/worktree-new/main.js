// The New worktree dialog on a key, for the focused space, in the focused
// pane's folder. A key can't pass a dialog its props. Opened with
// `mod.open:worktree-new`; this copy opens worktree-main, which starts new
// branches from origin's default branch, then closes itself.

import { View, div } from "gpui-kit";
import { checking, closeOverlay, focused, notify, openOverlay, panes, props } from "herdr";

export default class WorktreeNew extends View {
  init() {
    if (checking()) return;
    const f = focused();
    if (f?.space) {
      const folder = panes().find((p) => p.focused)?.cwd ?? f.cwd ?? undefined;
      openOverlay({ mod: "worktree-main", kind: "dialog", width: 460, height: 300, props: { space: f.space, folder } });
    } else notify({ title: "New worktree", body: "Open a space first.", level: "warning" });
    closeOverlay(props()?.overlay);
  }

  render() {
    return div();
  }
}
