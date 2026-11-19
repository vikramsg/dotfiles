// Herdr's New worktree dialog on a key, as the space menu and the + menu open
// it: for the focused space, in the focused pane's folder. A key can't pass the
// dialog its props. Opened with `mod.open:worktree-new`; this copy opens the
// dialog, then closes itself.

import { View, div } from "gpui-kit";
import { checking, closeOverlay, focused, notify, openOverlay, panes, props } from "herdr";

export default class WorktreeNew extends View {
  init() {
    if (checking()) return;
    const f = focused();
    if (f?.space) {
      const folder = panes().find((p) => p.focused)?.cwd ?? f.cwd ?? undefined;
      openOverlay({ mod: "worktree", kind: "dialog", width: 460, height: 280, props: { space: f.space, folder, action: "new" } });
    } else notify({ title: "New worktree", body: "Open a space first.", level: "warning" });
    closeOverlay(props()?.overlay);
  }

  render() {
    return div();
  }
}
