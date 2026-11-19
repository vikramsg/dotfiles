// Herdr's Open worktree dialog, the repo's checkouts, on a key, as the space
// menu and the + menu open it: for the focused space, in the focused pane's
// folder. A key can't pass the dialog its props. Opened with `mod.open:worktree-open`; this copy opens the
// dialog, then closes itself.

import { View, div } from "gpui-kit";
import { checking, closeOverlay, focused, notify, openOverlay, panes, props } from "herdr";

export default class WorktreeOpen extends View {
  init() {
    if (checking()) return;
    const f = focused();
    if (f?.space) {
      const folder = panes().find((p) => p.focused)?.cwd ?? f.cwd ?? undefined;
      openOverlay({ mod: "worktree", kind: "dialog", width: 560, height: 480, props: { space: f.space, folder, action: "open" } });
    } else notify({ title: "Open worktree", body: "Open a space first.", level: "warning" });
    closeOverlay(props()?.overlay);
  }

  render() {
    return div();
  }
}
