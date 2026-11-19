// The Files panel on a key, as the tab bar's Files button does it: shows the
// panel on Files, or hides it when Files is already showing. A key runs one
// command and this takes two. Opened with `mod.open:files-panel`; this copy
// acts, then closes itself.

import { View, div } from "gpui-kit";
import { checking, closeOverlay, layout, props, run } from "herdr";

function find(node, id) {
  if (node?.id === id) return node;
  for (const c of node?.children ?? []) {
    const hit = find(c, id);
    if (hit) return hit;
  }
  return null;
}

export default class FilesPanel extends View {
  init() {
    if (checking()) return;
    const root = layout();
    const panel = find(root, "panel"), body = find(root, "panel-body");
    if (panel && !panel.hidden && body?.active === "files") run("layout.hide", { id: "panel" });
    else {
      run("layout.select", { stack: "panel-body", child: "files" });
      run("layout.show", { id: "panel" });
    }
    closeOverlay(props()?.overlay);
  }

  render() {
    return div();
  }
}
