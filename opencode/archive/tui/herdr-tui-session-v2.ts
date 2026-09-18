// Based on the Herdr 0.8.2 integration, adapted for the OpenCode V2 TUI API.
// HERDR_INTEGRATION_ID=opencode-tui
// HERDR_INTEGRATION_VERSION=10

import net from "node:net";

import { Plugin } from "@opencode-ai/plugin/tui";

const SOURCE = "herdr:opencode";
const AGENT = "opencode";
const ROUTE_POLL_INTERVAL_MS = 100;
const SELECTION_RETRY_DELAYS_MS = [100, 400, 1_000];
let reportSequence = Date.now() * 1_000;

function nextReportSequence(): number {
  reportSequence += 1;
  return reportSequence;
}

function requestOnce(
  method: "pane.report_agent" | "pane.report_agent_session",
  params: Record<string, unknown>,
): Promise<void> {
  const paneID = process.env.HERDR_PANE_ID;
  const socketPath = process.env.HERDR_SOCKET_PATH;
  if (!paneID || !socketPath) return Promise.resolve();

  const socketEndpoint =
    process.platform === "win32" ? `\\\\.\\pipe\\${socketPath}` : socketPath;
  const request = {
    id: `${SOURCE}:tui:${Date.now()}:${Math.floor(Math.random() * 1_000_000)
      .toString()
      .padStart(6, "0")}`,
    method,
    params: {
      pane_id: paneID,
      source: SOURCE,
      agent: AGENT,
      seq: nextReportSequence(),
      ...params,
    },
  };

  return new Promise((resolve) => {
    const client = net.createConnection(socketEndpoint, () => {
      client.write(`${JSON.stringify(request)}\n`);
    });
    const finish = () => {
      client.destroy();
      resolve();
    };
    client.setTimeout(500, finish);
    client.on("data", finish);
    client.on("error", finish);
    client.on("end", finish);
    client.on("close", resolve);
  });
}

export default Plugin.define({
  id: "herdr.opencode.session-selection",

  async setup(ctx) {
    if (
      process.env.HERDR_ENV !== "1" ||
      !process.env.HERDR_SOCKET_PATH ||
      !process.env.HERDR_PANE_ID
    ) {
      return;
    }

    let selectedSessionID: string | undefined;
    let retryIndex = 0;
    let nextReportAt = 0;
    let reportPending = false;
    let requestChain = Promise.resolve();
    const request = (
      method: "pane.report_agent" | "pane.report_agent_session",
      params: Record<string, unknown>,
    ) => {
      const pending = requestChain.then(() => requestOnce(method, params));
      requestChain = pending.catch(() => {});
      return pending;
    };
    const reportState = async (state: "idle" | "working" | "blocked", sessionID: string) => {
      if (
        !selectedSessionID ||
        ctx.data.session.root(sessionID) !== selectedSessionID
      ) {
        return;
      }
      await request("pane.report_agent", {
        state,
        agent_session_id: selectedSessionID,
      });
    };
    const syncSelectedSession = async () => {
      const route = ctx.ui.router.current();
      if (route.type !== "session") {
        selectedSessionID = undefined;
        retryIndex = 0;
        nextReportAt = 0;
        return;
      }

      const sessionID = route.sessionID;
      const session = ctx.data.session.get(sessionID);
      if (!session || session.parentID) {
        selectedSessionID = undefined;
        retryIndex = 0;
        nextReportAt = 0;
        return;
      }
      if (sessionID !== selectedSessionID) {
        selectedSessionID = sessionID;
        retryIndex = 0;
        nextReportAt = 0;
      }
      if (reportPending || Date.now() < nextReportAt) return;

      const reportingSessionID = sessionID;
      reportPending = true;
      try {
        await request("pane.report_agent_session", {
          agent_session_id: reportingSessionID,
          session_start_source: "select",
        });
      } finally {
        reportPending = false;
      }
      if (selectedSessionID !== reportingSessionID) {
        retryIndex = 0;
        nextReportAt = 0;
        return;
      }
      const retryDelay = SELECTION_RETRY_DELAYS_MS[retryIndex];
      retryIndex += 1;
      nextReportAt =
        retryDelay === undefined
          ? Number.POSITIVE_INFINITY
          : Date.now() + retryDelay;
    };

    await syncSelectedSession();
    const routePoll = setInterval(
      () => void syncSelectedSession(),
      ROUTE_POLL_INTERVAL_MS,
    );
    const unsubscribes = [
      ctx.data.on("session.execution.started", (event) => {
        void reportState("working", event.data.sessionID);
      }),
      ctx.data.on("session.execution.succeeded", (event) => {
        void reportState("idle", event.data.sessionID);
      }),
      ctx.data.on("session.execution.interrupted", (event) => {
        void reportState("idle", event.data.sessionID);
      }),
      ctx.data.on("session.execution.failed", (event) => {
        void reportState("blocked", event.data.sessionID);
      }),
      ctx.data.on("session.status", (event) => {
        const state = event.data.status.type === "idle" ? "idle" : "working";
        void reportState(state, event.data.sessionID);
      }),
      ctx.data.on("session.idle", (event) => {
        void reportState("idle", event.data.sessionID);
      }),
      ctx.data.on("permission.asked", (event) => {
        void reportState("blocked", event.data.sessionID);
      }),
      ctx.data.on("permission.replied", (event) => {
        void reportState("working", event.data.sessionID);
      }),
      ctx.data.on("form.created", (event) => {
        void reportState("blocked", event.data.form.sessionID);
      }),
      ctx.data.on("form.replied", (event) => {
        void reportState("working", event.data.sessionID);
      }),
      ctx.data.on("form.cancelled", (event) => {
        void reportState("working", event.data.sessionID);
      }),
    ];

    return () => {
      clearInterval(routePoll);
      for (const unsubscribe of unsubscribes) unsubscribe();
    };
  },
});
