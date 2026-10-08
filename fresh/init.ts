// Only the Herdr sidebar needs the explorer focused immediately at startup.
if (editor.getEnv("FRESH_HERDR_SIDEBAR") === "1") {
  editor.on("ready", () => {
    editor.executeAction("focus_file_explorer");
  });
}

// Review panels replace the project tree while reading a diff. Buffer names
// are the public identities of the bundled review's panels, not file paths.
const reviewPanels = new Set(["*diff*", "*files*", "*comments*", "*toolbar*", "*sticky*"]);
const reviewWindows = new Map<number, { explorerWasVisible: boolean; filesShown: boolean }>();
let updatingReviewLayout = false;
let reviewLayoutPending = false;

async function updateReviewLayout() {
  if (updatingReviewLayout) {
    reviewLayoutPending = true;
    return;
  }
  updatingReviewLayout = true;
  try {
    await editor.flush();
    const windowId = editor.activeWindow();
    const buffer = editor.getBufferInfo(editor.getActiveBufferId());
    const reviewing = buffer?.is_virtual && (reviewPanels.has(buffer.name) || buffer.name.startsWith("*Review "));
    let state = reviewWindows.get(windowId);
    if (reviewing) {
      if (!state) {
        // With this profile's right-side explorer and no workspace dock,
        // unused columns beyond the editor splits belong to the project tree.
        const rightEdge = Math.max(...editor.listSplits().map(split => split.x + split.width));
        state = { explorerWasVisible: rightEdge < editor.getScreenSize().width, filesShown: false };
        reviewWindows.set(windowId, state);
        if (state.explorerWasVisible) editor.executeAction("toggle_file_explorer");
      }
      if (!state.filesShown) {
        state.filesShown = true;
        // The review exposes a show-files action through its filter command;
        // accepting the unchanged filter leaves the tree open without toggling
        // an already-visible panel closed on a repeated review.
        editor.executeAction("review_filter_files");
        editor.executeAction("review_filter_accept");
        editor.executeAction("review_focus_next");
      }
    } else if (state) {
      reviewWindows.delete(windowId);
      if (state.explorerWasVisible) {
        editor.executeAction("focus_file_explorer");
        editor.executeAction("focus_editor");
      }
    }
    await editor.flush();
  } finally {
    updatingReviewLayout = false;
    if (reviewLayoutPending) {
      reviewLayoutPending = false;
      scheduleReviewLayout();
    }
  }
}

let reviewLayoutTimer: number | null = null;
registerHandler("dotfiles_review_layout", () => {
  reviewLayoutTimer = null;
  void updateReviewLayout();
});
function scheduleReviewLayout() {
  if (reviewLayoutTimer !== null) editor.clearInterval(reviewLayoutTimer);
  reviewLayoutTimer = editor.setTimeout(100, "dotfiles_review_layout");
}

editor.on("active_buffer_changed", scheduleReviewLayout);
// Review commands load Git data asynchronously and can reuse an existing
// group without activating a new buffer. Reconcile once that load settles.
editor.on("post_command", (args) => {
  const action = typeof args.action === "string" ? args.action : JSON.stringify(args.action);
  if (action.includes("start_review_")) {
    scheduleReviewLayout();
  }
});
