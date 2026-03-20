# Overall Simplification Proposal Based on LazyVim Defaults

Based on the analysis of LazyVim defaults vs current `init.lua`, here is the complete plan to simplify the Neovim setup:

1.  **Replace multiple tools with `snacks.nvim`**: It can replace `telescope.nvim`, `neo-tree.nvim`, `toggleterm.nvim`, and `lazygit.nvim` with built-in, highly optimized components (`picker`, `explorer`, `terminal`, `lazygit`).
2.  **Replace completion engine with `blink.cmp`**: Replace the `nvim-cmp` ecosystem (which needs 5-6 dependencies) with the much faster and lighter `blink.cmp`.
3.  **Remove `Comment.nvim`**: Neovim 0.10+ has native `gc` commenting, making this plugin redundant.
4.  **Add `which-key.nvim`**: Replace the hardcoded 60-line keymap cheat sheet in comments with an interactive, dynamic popup.
5.  **Add `gitsigns.nvim`**: Replace heavy `diffview.nvim` workflows for line-by-line context with lightweight gutter signs.

# Phase 1: Implementing snacks.nvim

This phase replaces `telescope`, `neo-tree`, `toggleterm`, and `lazygit` with `snacks.nvim`.

## Step 1: Install and Configure `snacks.nvim`
Add `folke/snacks.nvim` to the lazy setup in `init.lua` with priority 1000. Enable the `picker`, `explorer`, `terminal`, `lazygit`, and `notifier` modules.

## Step 2: Migrate Keymaps
- **Search (Picker):** Map `<leader>sh`, `<leader>sf`, `<leader>sg`, `<leader>sw`, `<leader>sd`, `<leader>sr`, `<leader>s.`, `<leader><leader>`, `<leader>/`, `<leader>s/`, `<leader>sn`, `<leader>sF`, `<leader>sG` to their `Snacks.picker` equivalents.
- **Custom Grep (<leader>st):** Rewrite the custom input prompt to pass the extension to `Snacks.picker.grep({ glob = "*." .. ext, hidden = true })`.
- **LSP Attach Mappings:** Update `gd`, `gr`, `gI`, `<leader>D`, `<leader>ds`, `<leader>ws` in the `LspAttach` autocommand to use `Snacks.picker.lsp_definitions`, etc.
- **File Explorer:** Map `<leader>e` and `<leader>E` to `Snacks.explorer()`.
- **Custom Explorer Keymap:** Add an action in the `Snacks.explorer` config to copy the filename to clipboard (replacing the Neo-tree `Y` mapping).
- **Git:** Map `<leader>lg` to `Snacks.lazygit.open()`.
- **Terminal:** Map `<C-t>` to `Snacks.terminal.toggle()` configured for vertical split.

## Step 3: Rewrite MdPreview Command
Rewrite the custom `MdPreview` command. Instead of `toggleterm.terminal.Terminal:new`, use `Snacks.terminal()` configured to open `marxual` in a new tab or floating window. Maintain the necessary logic to clean up old instances.

## Step 4: Clean Up Old Plugins
Remove `telescope.nvim` (and all dependencies like `plenary.nvim`, `telescope-fzf-native.nvim`, `telescope-ui-select.nvim`, `nvim-web-devicons` if not needed elsewhere), `neo-tree.nvim` (and `nui.nvim`), `toggleterm.nvim`, and `lazygit.nvim` from `init.lua`. Remove `vim.keymap.set` calls pointing to these plugins.

## Step 5: End-to-End Verification
Use Neovim headless mode (`nvim --headless -c "..."`) to perform rigorous checks:
- Verify `snacks.nvim` is loaded.
- Verify `telescope.nvim`, `neo-tree.nvim`, `toggleterm.nvim`, `lazygit.nvim` are NOT loaded.
- Verify no compilation/parsing errors occur in `init.lua`.

# Phase 2: Completion, Comments, and Extras (blink.cmp, which-key, gitsigns)

## Step 1: Add blink.cmp
Replace `nvim-cmp` entirely with `blink.cmp`. It provides a native, zero-dependency autocomplete experience that is exponentially faster.

## Step 2: Remove Comment.nvim
Remove `Comment.nvim` since Neovim 0.10 has native `gc` visual/line commenting support.

## Step 3: Add which-key and gitsigns
Add `which-key.nvim` to replace the massive cheat sheet comment with dynamic keymap popups, and `gitsigns.nvim` for git gutter signs instead of opening full DiffViews for basic diffs.
