// Opens Ziggity in a popup over the shown tab, like the herdr/ `prefix+Shift+G`
// popup: started in the focused pane's folder on its space's machine, closed
// when Ziggity quits. Opened with `mod.open:ziggity-popup`; this copy only
// starts the terminal, opens the popup holding it and closes itself.

import { View, div } from "gpui-kit";
import { checking, closeOverlay, focused, hc, notify, openOverlay, props, spaces } from "herdr";

export default class ZiggityPopup extends View {
  init(_props, cx) {
    if (checking()) return;
    cx.spawn(async () => {
      try {
        await this.open();
      } catch (e) {
        notify({ title: "Ziggity popup", body: String(e?.message ?? e), level: "error" });
      } finally {
        closeOverlay(props()?.overlay);
      }
    });
  }

  async open() {
    const f = focused();
    const machine = spaces().find((s) => s.id === f?.space)?.machine ?? null;
    const args = ["run", "--json", "--bg", "--rm", "--no-parent"];
    if (f?.cwd) args.push("--cwd", f.cwd);
    if (machine) args.push("--on", machine);
    // The core's PATH lacks mise shims; zsh loads ~/.zshenv, which adds them.
    args.push("--", "/bin/zsh", "-c", "exec ziggity");
    const r = await hc(args);
    if (r.code !== 0) throw new Error(r.stderr.trim() || `hc run exited ${r.code}`);
    const { address } = JSON.parse(r.stdout);
    // Modal: a click beside it would close the popup and leave Ziggity running unseen.
    // The popup closes itself when Ziggity exits.
    openOverlay({
      kind: "dialog",
      modal: true,
      width: 0.9,
      height: 0.9,
      layout: { type: "block", content: { terminal: address } },
    });
  }

  render() {
    return div();
  }
}
