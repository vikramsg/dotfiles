-- Options

------------------------------------------------------------------------------
-- MASTER KEYMAP CHEAT SHEET
------------------------------------------------------------------------------
-- General & Navigation:
--   zz             : Center the cursor on screen
--   Space (Leader) : The prefix for most custom commands
--   <leader>1..9   : Jump to visible buffer 1 through 9 (Lualine index)
--   <leader><Left> : Previous buffer
--   <leader><Right>: Next buffer
--   <leader><Tab>  : Toggle alternate buffer
--   <C-h,j,k,l>    : Navigate between splits
--   <C-t>          : Toggle Terminal
--   <leader>d      : Delete without yanking
--   <leader>a      : Toggle Autocomplete (nvim-cmp)
--   <leader>f      : Format current buffer (Conform)
--   <leader>cp     : Copy absolute path of current file to clipboard
--
--
-- Git & Files:
--   <leader>gb : Show Git blame for current line
--   <leader>lg : LazyGit (Floating terminal)
--   <leader>rF : Rename current file with LSP updates
--
-- Search (Telescope):
--   <leader>sf : Search Files
--   <leader>sF : Search ALL Files (including git-ignored)
--   <leader>sg : Search by Grep (Live)
--   <leader>st : Search by Grep in File Type (prompts for extension)
--   <leader>sG : Search by Grep ALL (including git-ignored)
--   <leader><leader> : Search Open Buffers
--   <leader>sw : Search current Word
--   <leader>sd : Search Diagnostics
--   <leader>sh : Search Help tags
--   <C-d>      : Delete open buffers inside Telescope <Leader><Leader>
--
-- File Explorers:
--   <leader>e  : Toggle Neo-tree
--   In Snacks Explorer:
--     Y        : Copy filename to clipboard
--     e        : Toggle explorer fit width
--     .        : Toggle hidden files
--
-- LSP (Code Intelligence):
--   gd : Go to Definition
--   gr : Go to References
--   gI : Go to Implementation
--   rn : Rename variable
--   ca : Code Action
--   K  : Hover documentation
--
-- File navigation
--   gf : Go to File, if a filepath is available as text, for eg. in markdown
--
-- Markdown Renderer:
--   <leader>mp : Open viewer window on focused markdown file
--   Cmd + q : Close viewer
------------------------------------------------------------------------------

-- hacky way to ignore the vim global warnings issue
local vim = vim

vim.o.number = true
vim.o.relativenumber = false
vim.o.cursorline = true
vim.o.expandtab = true
vim.o.shiftwidth = 4
vim.o.tabstop = 4
vim.o.swapfile = false
vim.o.writebackup = false
vim.o.undofile = true
vim.o.cmdheight = 0 -- Remove gap between statusline and tmux
-- Sync clipboard between OS and Neovim.
-- Use OSC 52 for remote clipboard support (works over SSH/Tmux)
-- This avoids issues with broken xclip/x11 forwarding
vim.schedule(function()
	vim.opt.clipboard = "unnamedplus"
	if vim.fn.exists("$SSH_CONNECTION") == 1 or vim.fn.exists("$TMUX") == 1 then
		vim.g.clipboard = {
			name = "OSC 52",
			copy = {
				["+"] = require("vim.ui.clipboard.osc52").copy("+"),
				["*"] = require("vim.ui.clipboard.osc52").copy("*"),
			},
			paste = {
				["+"] = require("vim.ui.clipboard.osc52").paste("+"),
				["*"] = require("vim.ui.clipboard.osc52").paste("*"),
			},
		}
	end
end)

-- Save undo history
vim.opt.undofile = true

-- Case-insensitive searching UNLESS \C or one or more capital letters in the search term
vim.opt.ignorecase = true
vim.opt.smartcase = true
vim.o.inccommand = "split"

-- Optimize esc experience
-- Fast, reliable <Esc>
-- Does not help a lot but we have to do Esc twice it seems
vim.opt.timeout = true -- (default, but be explicit)
vim.opt.timeoutlen = 500 -- mapping sequences (adjust to taste)
vim.opt.ttimeout = true
vim.opt.ttimeoutlen = 10 -- 10–40 typical; lower = snappier Esc

-- Make Space the leader
vim.g.mapleader = " "

------------------------------------------------------------------------------
-- Vim keybindings
------------------------------------------------------------------------------

-- Jump to buffers based on their visual order (1-9) in Lualine
for i = 1, 9 do
	vim.keymap.set("n", "<leader>" .. i, function()
		require("lualine.components.buffers").buffer_jump(i)
	end, { desc = "Jump to visual buffer " .. i })
end

-- Keybinds to make split navigation easier.
--  Use CTRL+<hjkl> to switch between windows
--
----  See `:help wincmd` for a list of all window commands
vim.keymap.set("n", "<C-h>", "<C-w><C-h>", { desc = "Move focus to the left window" })
vim.keymap.set("n", "<C-k>", "<C-w><C-j>", { desc = "Move focus to the upper window" })
vim.keymap.set("n", "<C-j>", "<C-w><C-k>", { desc = "Move focus to the lower window" })
-- Does not seem to work
vim.keymap.set("n", "<C-b><Left>", "<C-w><C-h>", { desc = "Move focus to the left window" })
vim.keymap.set("n", "<C-l>", "<C-w><C-l>", { desc = "Move focus to the right window" })
-- Does not seem to work
vim.keymap.set("n", "<C-b><Right>", "<C-w><C-l>", { desc = "Move focus to the right window" })

-- Normal, visual, insert mode mappings for "beginning/end of line"
vim.keymap.set({ "n", "v", "i" }, "<Find>", "^", { desc = "Go to beginning of line" }) -- Fn + ←
vim.keymap.set({ "n", "v", "i" }, "<Select>", "$", { desc = "Go to end of line" }) -- Fn + →

-- Paste over selection without overwriting register
vim.keymap.set("x", "p", "P", { desc = "Paste without overwriting register" })

-- Prevent Ghostty/KKP <D-c> from falling back to plain `c` outside tmux
vim.keymap.set("n", "<D-c>", [[:<C-u>normal! "+yy<CR>]], { desc = "Copy line to system clipboard" })
vim.keymap.set("x", "<D-c>", [[:<C-u>normal! "+y<CR>]], { desc = "Copy selection to system clipboard" })

-- Delete without yanking (to the black hole register)
vim.keymap.set({ "n", "v" }, "<leader>d", [["_x]], { desc = "Delete character/selection without yanking" })

-- Copy absolute path of current file to clipboard
vim.keymap.set("n", "<leader>cp", function()
	local path = vim.fn.expand("%:p")
	vim.fn.setreg("+", path)
	vim.notify('Copied "' .. path .. '" to clipboard')
end, { desc = "Copy absolute path of current file to clipboard" })

-- Toggle alternate buffer (last opened buffer)
vim.keymap.set("n", "<leader><Tab>", "<C-^>", { desc = "Switch to alternate buffer" })

-- Cycle through buffers
vim.keymap.set("n", "<leader><Left>", "<cmd>bprevious<CR>", { desc = "Go to previous buffer" })
vim.keymap.set("n", "<leader><Right>", "<cmd>bnext<CR>", { desc = "Go to next buffer" })

--  Try it with `yap` in normal mode
--  See `:help vim.highlight.on_yank()`
vim.api.nvim_create_autocmd("TextYankPost", {
	desc = "Highlight when yanking (copying) text",
	group = vim.api.nvim_create_augroup("kickstart-highlight-yank", { clear = true }),
	callback = function()
		vim.highlight.on_yank()
	end,
})

-- Automatically equalize splits when terminal window resizes (e.g. tmux zoom)
vim.api.nvim_create_autocmd("VimResized", {
	desc = "Automatically equalize splits when terminal window resizes (e.g. tmux zoom)",
	group = vim.api.nvim_create_augroup("resize_splits", { clear = true }),
	callback = function()
		local current_tab = vim.api.nvim_get_current_tabpage()
		vim.cmd("tabdo wincmd =")
		vim.api.nvim_set_current_tabpage(current_tab)
	end,
})

------------------------------------------------------------------------------
-- Toggle autocomplete
------------------------------------------------------------------------------
-- initialize global var to false -> nvim-cmp turned off per default
-- Go look at nvim-cmp setup to see how this is used
vim.g.cmptoggle = false

vim.keymap.set("n", "<leader>a", "<cmd>lua vim.g.cmptoggle = not vim.g.cmptoggle<CR>", { desc = "toggle nvim-cmp" })

------------------------------------------------------------------------------
-- Plugins
------------------------------------------------------------------------------

-- Setup Lazy
local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
if not vim.loop.fs_stat(lazypath) then
	vim.fn.system({
		"git",
		"clone",
		"--filter=blob:none",
		"https://github.com/folke/lazy.nvim.git",
		"--branch=stable",
		lazypath,
	})
end
vim.opt.rtp:prepend(lazypath)

-- Setup plugins using lazy
local snacks_explorer_collapsed_width = 40

local function snacks_explorer_expanded_width()
	return math.max(60, math.floor(vim.o.columns * 0.35))
end

local function toggle_snacks_explorer_width(picker)
	if not (picker and picker.resolved_layout and picker.resolved_layout.layout) then
		return
	end

	local current_width = picker.resolved_layout.layout.width or snacks_explorer_collapsed_width
	if picker.list and picker.list.win and picker.list.win.win and vim.api.nvim_win_is_valid(picker.list.win.win) then
		current_width = vim.api.nvim_win_get_width(picker.list.win.win)
	end

	local target_width = current_width <= snacks_explorer_collapsed_width and snacks_explorer_expanded_width()
		or snacks_explorer_collapsed_width
	local layout = vim.deepcopy(picker.resolved_layout)
	layout.layout.width = target_width
	layout.layout.min_width = target_width
	layout.layout.max_width = target_width
	picker:set_layout(layout)
end

---Persist the explorer hidden filter on both live and initial picker state.
---Snacks rebuilds explorer items from `opts` during the current session and from
---`init_opts` during follow-up refreshes/navigation, so both need to match.
---@param picker snacks.Picker
---@param hidden boolean
local function set_snacks_explorer_hidden(picker, hidden)
	picker.opts.hidden = hidden
	if picker.init_opts then
		picker.init_opts.hidden = hidden
	end
end

---Persist the explorer ignored filter alongside the hidden toggle state.
---This repo keeps `.agents/tasks` git-ignored, so showing hidden directories
---without also unhiding ignored descendants leaves expanded hidden folders empty.
---@param picker snacks.Picker
---@param ignored boolean
local function set_snacks_explorer_ignored(picker, ignored)
	picker.opts.ignored = ignored
	if picker.init_opts then
		picker.init_opts.ignored = ignored
	end
end

---Toggle the explorer between normal view and "show everything" mode.
---The `.` mapping needs to flip both hidden and ignored filters so expanding a
---hidden directory continues to show nested ignored children like `.agents/tasks`.
---@param picker snacks.Picker
local function toggle_snacks_explorer_hidden(picker)
	local show_all = not picker.opts.hidden
	set_snacks_explorer_hidden(picker, show_all)
	set_snacks_explorer_ignored(picker, show_all)
	require("snacks.explorer.actions").update(picker, { refresh = true })
end

local function rename_current_file()
	Snacks.rename.rename_file({
		on_rename = function()
			vim.cmd("silent! wa")
		end,
	})
end

---Returns true when any segment in the given path is a dot-prefixed name.
---@param path string
---@return boolean
local function path_has_hidden_segment(path)
	local normalized = vim.fs.normalize(path)
	for segment in normalized:gmatch("[^/]+") do
		if segment ~= "." and segment ~= ".." and segment:sub(1, 1) == "." then
			return true
		end
	end
	return false
end

---Returns true when Git would ignore the path, including via an ignored parent directory.
---@param path string
---@return boolean
local function path_is_git_ignored(path)
	local result = vim.system({ "git", "-C", vim.fs.dirname(path), "check-ignore", "-q", "--", path }):wait()
	return result.code == 0
end

---Ensures the explorer is rooted correctly, opens the file path in the tree, and reveals it.
---@param picker snacks.Picker
---@param file string
local function reveal_file_in_explorer(picker, file)
	local actions = require("snacks.explorer.actions")
	local tree = require("snacks.explorer.tree")
	if not tree:in_cwd(picker:cwd(), file) then
		picker:set_cwd(vim.fs.dirname(file))
	end
	tree:open(file)
	actions.update(picker, { target = file, refresh = true })
end

---Reveals the current buffer's file in the explorer, enabling hidden/ignored filters when required.
local function reveal_current_file_in_explorer()
	local file = vim.fs.normalize(vim.fn.expand("%:p"))
	if file == "" then
		Snacks.explorer()
		return
	end

	local reveal_hidden = path_has_hidden_segment(file)
	local reveal_ignored = path_is_git_ignored(file)
	local explorer = Snacks.picker.get({ source = "explorer" })[1]

	if explorer then
		local filters_changed = false

		-- Hidden and ignored are independent filters: an ignored file may not be dot-prefixed,
		-- and hidden may already be enabled while ignored is still filtering the target out.
		if reveal_hidden and not explorer.opts.hidden then
			set_snacks_explorer_hidden(explorer, true)
			filters_changed = true
		end

		if reveal_ignored and not explorer.opts.ignored then
			set_snacks_explorer_ignored(explorer, true)
			filters_changed = true
		end

		if filters_changed then
			explorer.list:set_target()
			explorer:find()
		end
		reveal_file_in_explorer(explorer, file)
		return
	end

	Snacks.explorer({
		hidden = reveal_hidden,
		ignored = reveal_ignored,
		on_show = function(picker)
			reveal_file_in_explorer(picker, file)
		end,
	})
end

---Refresh Snacks explorer Git status after external Git tools update the index.
---Refs:
---  https://github.com/folke/snacks.nvim/pull/2175
---  https://git-scm.com/docs/git-status#_background_refresh
---  https://github.com/folke/snacks.nvim/issues/2773
---Snacks already runs background status with --no-optional-locks; this handles
---real Git writers like lazygit/gitui/CLI/Neogit that briefly hold .git/index.lock.
local function refresh_snacks_explorer_git_status_after_index_write()
	local pickers = Snacks.picker.get({ source = "explorer", tab = false })
	if #pickers == 0 then
		return
	end

	local git = require("snacks.explorer.git")
	local actions = require("snacks.explorer.actions")
	local uv = vim.uv or vim.loop

	local function refresh_picker_when_unlocked(picker, attempt)
		if not picker or picker.closed then
			return
		end

		local root = Snacks.git.get_root(picker:cwd())
		local lock = root and (root .. "/.git/index.lock") or nil

		-- External Git commands own the index lock while staging/committing/checking out.
		-- Ref: https://github.com/folke/snacks.nvim/issues/2773
		-- Defer instead of racing Snacks' status query against an active writer.
		if lock and uv.fs_stat(lock) then
			if attempt < 20 then
				vim.defer_fn(function()
					refresh_picker_when_unlocked(picker, attempt + 1)
				end, 100)
			end
			return
		end

		git.refresh(picker:cwd())
		actions.update(picker, { refresh = true, target = false })
	end

	for _, picker in ipairs(pickers) do
		refresh_picker_when_unlocked(picker, 0)
	end
end

require("lazy").setup({
	{
		"folke/snacks.nvim",
		priority = 1000,
		lazy = false,
		config = function(_, opts)
			-- Explorer picker keymaps resolve string actions through the global
			-- `snacks.picker.actions` table, so custom picker actions need to be
			-- registered there before the explorer is opened.
			require("snacks.picker.actions").toggle_explorer_width = toggle_snacks_explorer_width
			require("snacks.picker.actions").toggle_explorer_hidden = toggle_snacks_explorer_hidden
			require("snacks").setup(opts)

			local group = vim.api.nvim_create_augroup("dotfiles-snacks-explorer-git-refresh", { clear = true })

			vim.api.nvim_create_autocmd({ "FocusGained", "TermClose" }, {
				group = group,
				callback = function()
					-- Delay matches the Snacks explorer workaround for external Git writers:
					-- https://github.com/folke/snacks.nvim/issues/2773
					vim.defer_fn(refresh_snacks_explorer_git_status_after_index_write, 200)
				end,
			})

			vim.api.nvim_create_autocmd("User", {
				group = group,
				pattern = { "NeogitStatusRefresh", "NeogitStatus" },
				callback = function()
					vim.defer_fn(refresh_snacks_explorer_git_status_after_index_write, 200)
				end,
			})
		end,
		opts = {
			picker = {
				enabled = true,
				sources = {
					explorer = {
						win = {
							list = {
								keys = {
									["."] = "toggle_explorer_hidden",
									["e"] = "toggle_explorer_width",
									["gf"] = "explorer_focus",
								},
							},
						},
					},
				},
			},
			explorer = {
				enabled = true,
				replace_netrw = true,
				actions = {
					yank_filename = function(picker)
						local item = picker:current()
						if item and item.file then
							local path = item.file
							local filename = vim.fn.fnamemodify(path, ":t")
							vim.fn.setreg("+", filename)
							print("Copied filename: " .. filename)
						end
					end,
				},
				win = {
					list = {
						keys = {
							["."] = "toggle_explorer_hidden",
							["Y"] = "yank_filename",
							["e"] = "toggle_explorer_width",
							["gf"] = "explorer_focus",
						},
					},
				},
			},
			rename = { enabled = true },
			terminal = { enabled = true },
			lazygit = { enabled = true },
			notifier = { enabled = true },
		},
		keys = {
			{
				"<leader>gb",
				function()
					Snacks.git.blame_line()
				end,
				desc = "Git Blame Line",
			},
			{
				"<leader>sh",
				function()
					Snacks.picker.help()
				end,
				desc = "Search Help",
			},
			{
				"<leader>sk",
				function()
					Snacks.picker.keymaps()
				end,
				desc = "Search Keymaps",
			},
			{
				"<leader>sf",
				function()
					Snacks.picker.files()
				end,
				desc = "Search Files",
			},
			{
				"<leader>ss",
				function()
					Snacks.picker.pickers()
				end,
				desc = "Search Pickers",
			},
			{
				"<leader>rF",
				rename_current_file,
				desc = "Rename current file",
			},
			{
				"<leader>sw",
				function()
					Snacks.picker.grep_word()
				end,
				desc = "Search Word",
			},
			{
				"<leader>sg",
				function()
					Snacks.picker.grep()
				end,
				desc = "Search Grep",
			},
			{
				"<leader>st",
				function()
					local ext = vim.fn.input("Extension (e.g. yml): ")
					if ext ~= "" then
						Snacks.picker.grep({ glob = "*." .. ext, hidden = true })
					end
				end,
				desc = "Search Grep by Ext",
			},
			{
				"<leader>sd",
				function()
					Snacks.picker.diagnostics()
				end,
				desc = "Search Diagnostics",
			},
			{
				"<leader>sr",
				function()
					Snacks.picker.resume()
				end,
				desc = "Search Resume",
			},
			{
				"<leader>s.",
				function()
					Snacks.picker.recent()
				end,
				desc = "Search Recent",
			},
			{
				"<leader><leader>",
				function()
					Snacks.picker.buffers({
						win = { input = { keys = { ["<c-d>"] = { "bufdelete", mode = { "n", "i" } } } } },
					})
				end,
				desc = "Search Buffers",
			},
			{
				"<leader>/",
				function()
					Snacks.picker.lines()
				end,
				desc = "Fuzzily search in current buffer",
			},
			{
				"<leader>s/",
				function()
					Snacks.picker.grep_buffers()
				end,
				desc = "Search Open Files",
			},
			{
				"<leader>sn",
				function()
					Snacks.picker.files({ cwd = vim.fn.stdpath("config") })
				end,
				desc = "Search Neovim config",
			},
			{
				"<leader>sF",
				function()
					Snacks.picker.files({ hidden = true, ignored = true })
				end,
				desc = "Search All Files",
			},
			{
				"<leader>sG",
				function()
					Snacks.picker.grep({ hidden = true, ignored = true })
				end,
				desc = "Search All Grep",
			},
			{
				"<leader>e",
				function()
					Snacks.explorer()
				end,
				desc = "Toggle Explorer",
			},
			{
				"<leader>E",
				reveal_current_file_in_explorer,
				desc = "Reveal Explorer",
			},
			{
				"<leader>lg",
				function()
					Snacks.lazygit()
				end,
				desc = "LazyGit",
			},
			{
				"<C-t>",
				-- Snacks terminal uses a double-escape handler in terminal mode.
				-- With nested Neovim, a single <Esc> stays in the inner editor so
				-- `:w` saves normally, but a quick second <Esc> drops the outer
				-- terminal buffer into Normal mode. If you then run `:w`, the outer
				-- Neovim tries to write the terminal buffer itself and raises E382
				-- because terminal buftype buffers are not writable.
				function()
					Snacks.terminal.toggle(nil, { win = { position = "right", width = 65 } })
				end,
				mode = { "n", "t" },
				desc = "Toggle Terminal",
			},
			{
				"<leader>gd",
				function()
					Snacks.picker.git_diff()
				end,
				desc = "Git Diff (Hunks)",
			},
		},
	},
	{
		"folke/noice.nvim",
		dependencies = {
			"MunifTanjim/nui.nvim",
		},
	},
	{
		"smjonas/inc-rename.nvim",
	},

	-- Colorscheme - Look at kickstart.nvim/init.lua for more config help.
	{ -- You can easily change to a different colorscheme.
		"folke/tokyonight.nvim",
		priority = 1000, -- Make sure to load this before all the other start plugins.
		config = function()
			---@diagnostic disable-next-line: missing-fields
			require("tokyonight").setup({
				styles = {
					comments = { italic = false }, -- Disable italics in comments
				},
			})

			vim.cmd.colorscheme("tokyonight-night")
		end,
	},

	-- Highlight todo, notes, etc in comments
	{
		"folke/todo-comments.nvim",
		event = "VimEnter",
		dependencies = { "nvim-lua/plenary.nvim" },
		opts = {
			signs = false,
			keywords = {
				TODO = { alt = { "ToDo" } },
			},
		},
	},

	-- Treesitter owns structural indentation and reads each buffer's local shiftwidth when `=` reformats code.
	-- The repo default remains four spaces, but many existing files (including TypeScript/TSX) are already
	-- written with two-space indentation; guess-indent.nvim detects the current buffer's width/style from
	-- file contents on read so Treesitter preserves that file's established indentation level instead of
	-- forcing the global four-space default.
	{
		"NMAC427/guess-indent.nvim",
		event = "BufReadPost",
		opts = {},
	},

	{ -- Highlight, edit, and navigate code
		"nvim-treesitter/nvim-treesitter",
		branch = "main",
		lazy = false,
		build = ":TSUpdate",
		opts = {
			ensure_installed = {
				"bash",
				"c",
				"diff",
				"html",
				"javascript",
				"jsdoc",
				"lua",
				"luadoc",
				"markdown",
				"markdown_inline",
				"python",
				"query",
				"tsx",
				"typescript",
				"vim",
				"vimdoc",
			},
		},
		config = function(_, opts)
			-- nvim-treesitter `main` removed the old `nvim-treesitter.configs` module.
			-- LazyVim wraps this with helper functions; with plain lazy.nvim we keep the
			-- equivalent parser install and FileType feature-gating here instead.
			-- Reference: https://github.com/LazyVim/LazyVim/blob/ef272ff7cc9b53d48baf6544618b5923d65c0282/lua/lazyvim/plugins/treesitter.lua
			local treesitter = require("nvim-treesitter")
			treesitter.setup({
				-- Keep generated parsers out of the plugin checkout so stale parser .so
				-- files cannot shadow Neovim's runtime or freshly installed parsers.
				install_dir = vim.fn.stdpath("data") .. "/site",
			})

			local ensure_installed = opts.ensure_installed or {}
			local installed = treesitter.get_installed("parsers")
			local missing = vim.tbl_filter(function(lang)
				return not vim.tbl_contains(installed, lang)
			end, ensure_installed)

			if #missing > 0 then
				treesitter.install(missing, { summary = true })
			end

			local function has_query(lang, query)
				local ok, parsed_query = pcall(vim.treesitter.query.get, lang, query)
				return ok and parsed_query ~= nil
			end

			vim.api.nvim_create_autocmd("FileType", {
				group = vim.api.nvim_create_augroup("dotfiles-treesitter", { clear = true }),
				callback = function(event)
					local lang = vim.treesitter.language.get_lang(event.match) or event.match
					if not vim.tbl_contains(ensure_installed, lang) then
						return
					end

					if has_query(lang, "highlights") then
						pcall(vim.treesitter.start, event.buf)
					end

					if has_query(lang, "indents") then
						vim.bo[event.buf].indentexpr = "v:lua.require'nvim-treesitter'.indentexpr()"
					end
				end,
			})
		end,
	},

	------------------------------------------------------------------------------
	-- LSP Setup -----------------------------------------------------------------
	------------------------------------------------------------------------------
	{
		-- Main LSP Configuration
		-- Refer to kickstart nvim for more
		"neovim/nvim-lspconfig",
		dependencies = {
			-- Automatically install LSPs and related tools to stdpath for Neovim
			-- Mason is the packages manager for lsp. It installs the required servers, for example pyright etc.
			{ "williamboman/mason.nvim", opts = {} },
			"williamboman/mason-lspconfig.nvim",
			"WhoIsSethDaniel/mason-tool-installer.nvim",

			-- Useful status updates for LSP.
			{ "j-hui/fidget.nvim", opts = {} },

			-- Allows extra capabilities provided by nvim-cmp
			"hrsh7th/cmp-nvim-lsp",
		},
		config = function()
			-- LSP provides Neovim with features like:
			--  - Go to definition
			--  - Find references
			--  - Autocompletion
			--  - Symbol Search
			--  - and more!
			vim.api.nvim_create_autocmd("LspAttach", {
				group = vim.api.nvim_create_augroup("kickstart-lsp-attach", { clear = true }),
				callback = function(event)
					-- NOTE: Remember that Lua is a real programming language, and as such it is possible
					-- to define small helper and utility functions so you don't have to repeat yourself.
					--
					-- In this case, we create a function that lets us more easily define mappings specific
					-- for LSP related items. It sets the mode, buffer and description for us each time.
					local map = function(keys, func, desc, mode, opts)
						mode = mode or "n"
						opts = vim.tbl_extend("force", { buffer = event.buf, desc = "LSP: " .. desc }, opts or {})
						vim.keymap.set(mode, keys, func, opts)
					end

					-- Jump to the definition of the word under your cursor.
					--  This is where a variable was first declared, or where a function is defined, etc.
					--  To jump back, press <C-t>.
					map("gd", function()
						Snacks.picker.lsp_definitions()
					end, "[G]oto [D]efinition")

					-- Find references for the word under your cursor.
					map("gr", function()
						Snacks.picker.lsp_references()
					end, "[G]oto [R]eferences")

					-- Jump to the implementation of the word under your cursor.
					--  Useful when your language has ways of declaring types without an actual implementation.
					map("gI", function()
						Snacks.picker.lsp_implementations()
					end, "[G]oto [I]mplementation")

					-- Jump to the type of the word under your cursor.
					--  Useful when you're not sure what type a variable is and you want to see
					--  the definition of its *type*, not where it was *defined*.
					map("<leader>D", function()
						Snacks.picker.lsp_type_definitions()
					end, "Type [D]efinition")

					-- Fuzzy find all the symbols in your current document.
					--  Symbols are things like variables, functions, types, etc.
					map("<leader>ds", function()
						Snacks.picker.lsp_symbols()
					end, "[D]ocument [S]ymbols")

					-- Fuzzy find all the symbols in your current workspace.
					--  Similar to document symbols, except searches over your entire project.
					map("<leader>ws", function()
						Snacks.picker.lsp_workspace_symbols()
					end, "[W]orkspace [S]ymbols")

					-- Rename the variable under your cursor.
					--  Most Language Servers support renaming across files, etc.
					map("<leader>rn", function()
						return ":IncRename " .. vim.fn.expand("<cword>")
					end, "[R]e[n]ame", "n", { expr = true })

					-- Execute a code action, usually your cursor needs to be on top of an error
					-- or a suggestion from your LSP for this to activate.
					map("<leader>ca", vim.lsp.buf.code_action, "[C]ode [A]ction", { "n", "x" })

					-- Alternative mapping in case the above doesn't work
					map("<M-]>777;CmdDot", vim.lsp.buf.code_action, "Code Action (Leader+.)", { "n", "x" })

					-- FIXME: Add missing import - dedicated keybinding for import suggestions
					-- This is enabled for ty but does not seem to work

					-- WARN: This is not Goto Definition, this is Goto Declaration.
					--  For example, in C this would take you to the header.
					map("gD", vim.lsp.buf.declaration, "[G]oto [D]eclaration")

					-- This function resolves a difference between neovim nightly (version 0.11) and stable (version 0.10)
					---@param client vim.lsp.Client
					---@param method vim.lsp.protocol.Method
					---@param bufnr? integer some lsp support methods only in specific files
					---@return boolean
					local function client_supports_method(client, method, bufnr)
						if vim.fn.has("nvim-0.11") == 1 then
							return client:supports_method(method, bufnr)
						else
							return client.supports_method(method, { bufnr = bufnr })
						end
					end

					-- The following two autocommands are used to highlight references of the
					-- word under your cursor when your cursor rests there for a little while.
					--    See `:help CursorHold` for information about when this is executed
					--
					-- When you move your cursor, the highlights will be cleared (the second autocommand).
					local client = vim.lsp.get_client_by_id(event.data.client_id)
					if
						client
						and client_supports_method(
							client,
							vim.lsp.protocol.Methods.textDocument_documentHighlight,
							event.buf
						)
					then
						local highlight_augroup =
							vim.api.nvim_create_augroup("kickstart-lsp-highlight", { clear = false })
						vim.api.nvim_create_autocmd({ "CursorHold", "CursorHoldI" }, {
							buffer = event.buf,
							group = highlight_augroup,
							callback = vim.lsp.buf.document_highlight,
						})

						vim.api.nvim_create_autocmd({ "CursorMoved", "CursorMovedI" }, {
							buffer = event.buf,
							group = highlight_augroup,
							callback = vim.lsp.buf.clear_references,
						})

						vim.api.nvim_create_autocmd("LspDetach", {
							group = vim.api.nvim_create_augroup("kickstart-lsp-detach", { clear = true }),
							callback = function(event2)
								vim.lsp.buf.clear_references()
								vim.api.nvim_clear_autocmds({ group = "kickstart-lsp-highlight", buffer = event2.buf })
							end,
						})
					end

					-- The following code creates a keymap to toggle inlay hints in your
					-- code, if the language server you are using supports them
					--
					-- This may be unwanted, since they displace some of your code
					if
						client
						and client_supports_method(client, vim.lsp.protocol.Methods.textDocument_inlayHint, event.buf)
					then
						map("<leader>th", function()
							vim.lsp.inlay_hint.enable(not vim.lsp.inlay_hint.is_enabled({ bufnr = event.buf }))
						end, "[T]oggle Inlay [H]ints")
					end
				end,
			})

			-- Diagnostic Config
			-- See :help vim.diagnostic.Opts
			vim.diagnostic.config({
				virtual_text = false, -- disable the diagnostic text on the same line
				underline = true,
				update_in_insert = false, -- Prevents diagnostic from updating while typing in insert mode

				virtual_lines = {
					current_line = true,
				}, -- Only show if you are on the line with the error
				float = false,
				signs = {
					text = {
						[vim.diagnostic.severity.ERROR] = "󰅚 ",
						[vim.diagnostic.severity.WARN] = "󰀪 ",
						[vim.diagnostic.severity.INFO] = "󰋽 ",
						[vim.diagnostic.severity.HINT] = "󰌶 ",
					},
					numhl = {
						[vim.diagnostic.severity.ERROR] = "ErrorMsg",
						[vim.diagnostic.severity.WARN] = "WarningMsg",
					},
				},
			})

			-- LSP servers and clients are able to communicate to each other what features they support.
			--  By default, Neovim doesn't support everything that is in the LSP specification.
			--  When you add nvim-cmp, luasnip, etc. Neovim now has *more* capabilities.
			--  So, we create new capabilities with nvim cmp, and then broadcast that to the servers.
			local capabilities = vim.lsp.protocol.make_client_capabilities()
			capabilities = vim.tbl_deep_extend("force", capabilities, require("cmp_nvim_lsp").default_capabilities())
			capabilities.workspace = capabilities.workspace or {}
			capabilities.workspace.fileOperations = {
				didRename = true,
				willRename = true,
			}

			-- Enable the following language servers
			--  Feel free to add/remove any LSPs that you want here. They will automatically be installed.
			--
			local servers = {
				-- clangd = {},
				-- gopls = {},

				ruff = {},
				ty = {
					settings = {
						ty = {
							completions = {
								autoImport = true,
							},
						},
					},
				},
				ts_ls = {}, -- TypeScript and JavaScript LSP

				lua_ls = {
					-- cmd = { ... },
					-- filetypes = { ... },
					-- capabilities = {},
					settings = {
						Lua = {
							completion = {
								callSnippet = "Replace",
							},
							runtime = {
								version = "LuaJIT",
							},
							diagnostics = {
								globals = { "vim" },
							},
							workspace = {
								library = vim.api.nvim_get_runtime_file("", true),
								checkThirdParty = false,
							},
							telemetry = {
								enable = false,
							},
						},
					},
				},
			}

			-- Ensure the servers and tools above are installed
			--
			-- To check the current status of installed tools and/or manually install
			-- other tools, you can run
			--    :Mason
			--
			-- You can press `g?` for help in this menu.
			--
			-- `mason` had to be setup earlier: to configure its options see the
			-- `dependencies` table for `nvim-lspconfig` above.
			--
			-- You can add other tools here that you want Mason to install
			-- for you, so that they are available from within Neovim.
			local ensure_installed = vim.tbl_keys(servers or {})
			vim.list_extend(ensure_installed, {
				"stylua", -- Used to format Lua code
				"prettierd", -- Faster formatter for JS/TS/JSON
			})
			require("mason-tool-installer").setup({ ensure_installed = ensure_installed })

			for server_name, server in pairs(servers) do
				server.capabilities = vim.tbl_deep_extend("force", {}, capabilities, server.capabilities or {})
				vim.lsp.config(server_name, server)
				vim.lsp.enable(server_name)
			end

			require("mason-lspconfig").setup({
				ensure_installed = {}, -- explicitly set to an empty table (Kickstart populates installs via mason-tool-installer)
				automatic_enable = false,
			})
		end,
	},

	{ -- Autoformat
		"stevearc/conform.nvim",
		event = { "BufWritePre" },
		cmd = { "ConformInfo" },
		keys = {
			{
				"<leader>f",
				function()
					require("conform").format({ async = true, lsp_format = "fallback" })
				end,
				mode = "",
				desc = "[F]ormat buffer",
			},
		},
		opts = {
			notify_on_error = false,
			format_on_save = function(bufnr)
				-- Disable "format_on_save lsp_fallback" for languages that don't
				-- have a well standardized coding style. You can add additional
				-- languages here or re-enable it for the disabled ones.
				local disable_filetypes = { c = true, cpp = true }
				local lsp_format_opt
				if disable_filetypes[vim.bo[bufnr].filetype] then
					lsp_format_opt = "never"
				else
					lsp_format_opt = "fallback"
				end
				return {
					timeout_ms = 2000,
					lsp_format = lsp_format_opt,
				}
			end,
			formatters_by_ft = {
				json = { "prettierd" },
				jsonc = { "prettierd" },
				json5 = { "prettierd" },
				lua = { "stylua" },
				-- Conform can also run multiple formatters sequentially
				python = { -- To fix auto-fixable lint errors.
					"ruff_fix",
					-- To run the Ruff formatter.
					"ruff_format",
					-- To organize the imports.
					"ruff_organize_imports",
				},
				--
				-- You can use 'stop_after_first' to run the first available formatter from the list
				javascript = { "prettierd" },
				typescript = { "prettierd" },
				javascriptreact = { "prettierd" },
				typescriptreact = { "prettierd" },
			},
		},
	},

	{ -- Autocompletion
		"hrsh7th/nvim-cmp",
		event = "InsertEnter",
		dependencies = {
			-- Snippet Engine & its associated nvim-cmp source
			{
				"L3MON4D3/LuaSnip",
				build = (function()
					-- Build Step is needed for regex support in snippets.
					-- This step is not supported in many windows environments.
					-- Remove the below condition to re-enable on windows.
					if vim.fn.has("win32") == 1 or vim.fn.executable("make") == 0 then
						return
					end
					return "make install_jsregexp"
				end)(),
				dependencies = {
					-- `friendly-snippets` contains a variety of premade snippets.
					--    See the README about individual language/framework/plugin snippets:
					--    https://github.com/rafamadriz/friendly-snippets
					-- {
					--   'rafamadriz/friendly-snippets',
					--   config = function()
					--     require('luasnip.loaders.from_vscode').lazy_load()
					--   end,
					-- },
				},
			},
			"saadparwaiz1/cmp_luasnip",

			-- Adds other completion capabilities.
			--  nvim-cmp does not ship with all sources by default. They are split
			--  into multiple repos for maintenance purposes.
			"hrsh7th/cmp-nvim-lsp",
			"hrsh7th/cmp-path",
			"hrsh7th/cmp-nvim-lsp-signature-help",
		},
		config = function()
			-- See `:help cmp`
			local cmp = require("cmp")
			local luasnip = require("luasnip")
			luasnip.config.setup({})

			cmp.setup({
				enabled = function()
					return vim.g.cmptoggle
				end,

				snippet = {
					expand = function(args)
						luasnip.lsp_expand(args.body)
					end,
				},
				-- Make completions less aggressive.
				-- Start completions only after 2 entries, and only show 10 at a time.
				completion = {
					completeopt = "menu,menuone,noinsert",
					keyword_length = 2,
				},
				performance = {
					max_view_entries = 10,
				},

				-- For an understanding of why these mappings were
				-- chosen, you will need to read `:help ins-completion`
				--
				-- No, but seriously. Please read `:help ins-completion`, it is really good!
				mapping = cmp.mapping.preset.insert({
					-- Scroll the documentation window [b]ack / [f]orward
					["<C-b>"] = cmp.mapping.scroll_docs(-4),
					["<C-f>"] = cmp.mapping.scroll_docs(4),

					-- If you prefer more traditional completion keymaps,
					-- you can uncomment the following lines
					["<CR>"] = cmp.mapping.confirm({ select = true }),
					["<Tab>"] = cmp.mapping.select_next_item(),
					["<S-Tab>"] = cmp.mapping.select_prev_item(),

					-- Manually trigger a completion from nvim-cmp.
					--  Generally you don't need this, because nvim-cmp will display
					--  completions whenever it has completion options available.
					["<C-Space>"] = cmp.mapping.complete({}),

					-- For more advanced Luasnip keymaps (e.g. selecting choice nodes, expansion) see:
					--    https://github.com/L3MON4D3/LuaSnip?tab=readme-ov-file#keymaps
				}),
				sources = {
					{
						name = "lazydev",
						-- set group index to 0 to skip loading LuaLS completions as lazydev recommends it
						group_index = 0,
					},
					-- These are the sources from which autocompletions work
					{ name = "nvim_lsp" },

					{ name = "luasnip" },
					{ name = "path" },
					{ name = "nvim_lsp_signature_help" },
				},
			})
		end,
	},

	-- Tmux + vim navigation
	{
		"christoomey/vim-tmux-navigator",
	},

	-- Statusline with git branch
	{
		"nvim-lualine/lualine.nvim",
		dependencies = { "nvim-tree/nvim-web-devicons" },
		config = function()
			require("lualine").setup({
				sections = {
					-- Setting the letter after lualine decides which position the status is at.
					-- Only a,b,c x,y,z are available
					lualine_a = { "branch" },
					lualine_b = {
						{
							"buffers",
							mode = 2, -- Shows buffer index + buffer name
						},
					},
					lualine_x = {
						{
							function()
								return vim.g.cmptoggle and "AC:ON" or "AC:OFF"
							end,
							color = function()
								return vim.g.cmptoggle and { fg = "#00ff00" } or { fg = "#ff0000" }
							end,
						},
					},
				},
				-- Display custom hints in Neo-tree's statusline
				-- This explicitly shows the [e] hint without needing to open the help menu
				extensions = {
					{
						sections = {
							lualine_a = {
								function()
									return "Neo-tree"
								end,
							},
							lualine_b = {
								function()
									return "[e] fit width"
								end,
							},
						},
						filetypes = { "snacks_explorer" },
					},
				},
			})
		end,
	},

	-- autopairs plugin
	{
		"windwp/nvim-autopairs",
		event = "InsertEnter",
		opts = {},
	},

	-- "gc" to comment visual regions/lines
	{ "numToStr/Comment.nvim", opts = {} },
})

require("noice").setup({
	presets = {
		inc_rename = true,
	},
	cmdline = {
		format = {
			IncRename = { icon = "󰑕" },
		},
	},
})

require("inc_rename").setup({
	post_hook = function()
		vim.cmd("silent! wa")
	end,
})
