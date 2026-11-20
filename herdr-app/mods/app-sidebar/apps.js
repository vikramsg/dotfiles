// The apps the sidebar can show. Bind a key to `app-sidebar.toggle:<name>` in
// keys.json. Each is a command for `zsh -lc` (so Homebrew and mise are on its
// PATH), run on the tab's machine in its focused pane's folder.

export const APPS = {
  // Listens where `app-sidebar.open:<path>` sends files (a stale socket of the tab's is removed).
  nvim: 'rm -f "$APP_SIDEBAR_SOCK"; exec nvim --listen "$APP_SIDEBAR_SOCK"',
  // The terminal Herdr's reviewr plugin, run on its own with its config. Its
  // install folder comes from `herdr plugin list`: updates install elsewhere.
  reviewr: [
    `root=$(herdr plugin list --json | jq -r '.result.plugins[] | select(.plugin_id == "persiyanov.reviewr") | .plugin_root')`,
    `HERDR_PLUGIN_ID=persiyanov.reviewr HERDR_PLUGIN_CONFIG_DIR="$(herdr plugin config-dir persiyanov.reviewr)" exec "$root/bin/herdr-reviewr"`,
  ].join(" && "),
};
