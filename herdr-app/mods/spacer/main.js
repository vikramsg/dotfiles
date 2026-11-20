// Draws nothing. A layout block must hold content, so this fills one that only
// takes up room: in main-copy's status bar it keeps usage-limits off the right edge.

import { View, div } from "gpui-kit";

export default class Spacer extends View {
  render() {
    return div();
  }
}
