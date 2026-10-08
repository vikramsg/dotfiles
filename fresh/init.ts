// Only the Herdr sidebar needs the explorer focused immediately at startup.
if (editor.getEnv("FRESH_HERDR_SIDEBAR") === "1") {
  editor.on("ready", () => {
    editor.executeAction("focus_file_explorer");
  });
}
