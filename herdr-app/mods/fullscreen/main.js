// macOS full screen on a key. Herdr's commands only maximize the window
// (`window.maximize`), so this calls GPUI's toggle directly. Opened with
// `mod.open:fullscreen`; this copy toggles, then closes itself.

import { View, div } from "gpui-kit";
import { checking, closeOverlay, props } from "herdr";

export default class Fullscreen extends View {
  init() {
    if (checking()) return;
    window.toggle_fullscreen();
    closeOverlay(props()?.overlay);
  }

  render() {
    return div();
  }
}
