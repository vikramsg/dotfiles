import { writeSync } from "node:fs";

import { Plugin } from "@opencode-ai/plugin/tui";

export const ring = (): void => {
  writeSync(process.stdout.fd, "\x07");
};

export default Plugin.define({
  id: "dotfiles.zed-bell-v2",

  setup(ctx) {
    const offSucceeded = ctx.data.on("session.execution.succeeded", ring);
    const offFailed = ctx.data.on("session.execution.failed", ring);
    const offInterrupted = ctx.data.on("session.execution.interrupted", ring);
    const offPermission = ctx.data.on("permission.asked", ring);

    return () => {
      offSucceeded();
      offFailed();
      offInterrupted();
      offPermission();
    };
  },
});
