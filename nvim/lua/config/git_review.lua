local M = {}

local codediff_next_compare_mode

local function open_codediff_comparison(git_root, mode)
	codediff_next_compare_mode = mode
	local command = "CodeDiff --repo " .. vim.fn.fnameescape(git_root)
	if mode == "main" then
		command = command .. " main..."
	end
	vim.cmd(command)
end

local function open_review(name, open_comparison)
	local git_root = Snacks.git.get_root()
	if not git_root then
		vim.notify(name .. " requires a Git repository", vim.log.levels.ERROR)
		return
	end

	local status = vim.system({ "git", "status", "--porcelain", "--untracked-files=normal" }, {
		cwd = git_root,
		text = true,
	}):wait()
	if status.code ~= 0 then
		vim.notify(status.stderr or "Unable to read Git status", vim.log.levels.ERROR)
		return
	end

	if status.stdout ~= "" then
		open_comparison(git_root, "HEAD")
		return
	end

	local against_main = vim.system({ "git", "diff", "--quiet", "main...HEAD", "--" }, {
		cwd = git_root,
		text = true,
	}):wait()
	if against_main.code == 1 then
		open_comparison(git_root, "main")
	elseif against_main.code == 0 then
		vim.notify("No changes since HEAD or since branching from main", vim.log.levels.INFO)
	else
		vim.notify(against_main.stderr or "Unable to compare against main", vim.log.levels.ERROR)
	end
end

function M.open_codediff()
	open_review("CodeDiff", open_codediff_comparison)
end

local function toggle_codediff_comparison()
	local lifecycle = require("codediff.ui.lifecycle")
	local tabpage = vim.api.nvim_get_current_tabpage()
	local session = lifecycle.get_session(tabpage)
	if not session then
		vim.notify("No active CodeDiff view", vim.log.levels.ERROR)
		return
	end

	local mode = vim.t[tabpage].dotfiles_codediff_compare_mode
	local next_mode = mode == "main" and "HEAD" or "main"
	local git_root = session.git_root
	if not lifecycle.close(tabpage) then
		return
	end

	vim.schedule(function()
		open_codediff_comparison(git_root, next_mode)
	end)
end

-- Reuse an editor split rather than replacing whichever scratch/explorer split
-- was last focused in the previous tab. Keep the review tab open for returning.
local function edit_review_file(tabpage, target_file, cursor)
	if not target_file or vim.fn.filereadable(target_file) ~= 1 then
		vim.notify("No editable working file for this diff", vim.log.levels.WARN)
		return
	end

	local tabs = vim.api.nvim_list_tabpages()
	local current_index
	for index, tab in ipairs(tabs) do
		if tab == tabpage then
			current_index = index
			break
		end
	end

	local target_tab
	if not current_index or current_index == 1 then
		vim.cmd("tabnew")
		target_tab = vim.api.nvim_get_current_tabpage()
		vim.cmd("tabmove 0")
	else
		target_tab = tabs[current_index - 1]
		vim.api.nvim_set_current_tabpage(target_tab)
	end

	local target_win
	local fallback_win
	for _, win in ipairs(vim.api.nvim_tabpage_list_wins(target_tab)) do
		local config = vim.api.nvim_win_get_config(win)
		if config.relative == "" then
			fallback_win = fallback_win or win
			local bufnr = vim.api.nvim_win_get_buf(win)
			local name = vim.api.nvim_buf_get_name(bufnr)
			if vim.bo[bufnr].buftype == "" and name ~= "" then
				target_win = win
				if vim.fs.normalize(name) == vim.fs.normalize(target_file) then
					break
				end
			end
		end
	end
	target_win = target_win or fallback_win
	if not target_win or not vim.api.nvim_win_is_valid(target_win) then
		vim.notify("No editor window available", vim.log.levels.ERROR)
		return
	end

	vim.api.nvim_set_current_win(target_win)
	vim.cmd("edit " .. vim.fn.fnameescape(target_file))
	local line = math.min(cursor[1], vim.api.nvim_buf_line_count(0))
	local text = vim.api.nvim_buf_get_lines(0, line - 1, line, false)[1] or ""
	vim.api.nvim_win_set_cursor(0, { line, math.min(cursor[2], #text) })
end

local function edit_codediff_file()
	local lifecycle = require("codediff.ui.lifecycle")
	local tabpage = vim.api.nvim_get_current_tabpage()
	if not lifecycle.get_session(tabpage) then
		return
	end
	local _, modified = lifecycle.get_paths(tabpage)
	edit_review_file(tabpage, modified and modified.absolute, vim.api.nvim_win_get_cursor(0))
end

function M.setup_codediff(opts)
	require("codediff").setup(opts)
	local group = vim.api.nvim_create_augroup("dotfiles-codediff-help", { clear = true })

	local function set_custom_keymaps(tabpage)
		local lifecycle = require("codediff.ui.lifecycle")
		lifecycle.set_tab_keymap(
			tabpage,
			"n",
			"B",
			toggle_codediff_comparison,
			{ desc = "Toggle CodeDiff HEAD/Main Comparison" }
		)
		lifecycle.set_tab_keymap(tabpage, "n", "gf", edit_codediff_file, { desc = "Edit File at Current Line" })
	end

	vim.api.nvim_create_autocmd("User", {
		group = group,
		pattern = "CodeDiffOpen",
		callback = function(args)
			local tabpage = args.data.tabpage
			local session = require("codediff.ui.lifecycle").get_session(tabpage)
			local mode = codediff_next_compare_mode or (session.original_revision and "custom" or "HEAD")
			codediff_next_compare_mode = nil
			vim.t[tabpage].dotfiles_codediff_compare_mode = mode
			set_custom_keymaps(tabpage)
			vim.notify("B: HEAD/main | [/] hunks | gf: edit | g?: help | q: close", vim.log.levels.INFO, {
				title = "CodeDiff",
				timeout = 10000,
			})
		end,
	})

	vim.api.nvim_create_autocmd("User", {
		group = group,
		pattern = "CodeDiffFileSelect",
		callback = function(args)
			local tabpage = args.data.tabpage
			local expected_path = vim.fs.normalize(args.data.path)
			local attempts = 0
			local function bind_when_selected()
				attempts = attempts + 1
				local lifecycle = require("codediff.ui.lifecycle")
				local original, modified = lifecycle.get_paths(tabpage)
				local current_path = (modified and modified.relative) or (original and original.relative)
				if current_path and vim.fs.normalize(current_path) == expected_path then
					set_custom_keymaps(tabpage)
					return
				end
				if attempts < 100 and vim.api.nvim_tabpage_is_valid(tabpage) then
					vim.defer_fn(bind_when_selected, 50)
				end
			end
			vim.schedule(bind_when_selected)
		end,
	})
end

-- Keep all unchanged lines in the buffer, using Differ's native context folds.
-- The preference belongs to the review tab, not an individual file/column.
local function apply_differ_folds(win)
	local compact = vim.t[vim.api.nvim_win_get_tabpage(win)].dotfiles_differ_compact ~= false
	vim.api.nvim_win_call(win, function()
		vim.cmd(compact and "normal! zM" or "normal! zR")
	end)
end

local function toggle_differ_context()
	vim.t.dotfiles_differ_compact = vim.t.dotfiles_differ_compact == false
	for _, win in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
		if vim.bo[vim.api.nvim_win_get_buf(win)].filetype == "differdiff" then
			apply_differ_folds(win)
		end
	end
end

local watched_diffs, pending_folds = {}, {}
local function schedule_differ_folds(buf)
	if pending_folds[buf] then
		return
	end
	pending_folds[buf] = true
	-- File switches, refreshes, discards, and layout changes rebuild folds open.
	-- Wait until that render finishes; don't patch Differ's private methods.
	vim.schedule(function()
		pending_folds[buf] = nil
		if vim.api.nvim_buf_is_valid(buf) then
			for _, win in ipairs(vim.fn.win_findbuf(buf)) do
				apply_differ_folds(win)
			end
		end
	end)
end

local function open_differ_comparison(git_root, mode, compact)
	-- Differ chooses its repository from the file or cwd and opens a new tab.
	-- Keep the invoking window's directory unchanged, including its scope.
	local origin = vim.api.nvim_get_current_win()
	local cwd, scope = vim.fn.getcwd(), vim.fn.haslocaldir()
	vim.cmd("lcd " .. vim.fn.fnameescape(git_root))
	local ok, err = pcall(function()
		require("differ").open(mode == "main" and "main..." or "HEAD")
	end)
	if vim.api.nvim_win_is_valid(origin) then
		vim.api.nvim_win_call(origin, function()
			local command = scope == 1 and "lcd" or (scope == 2 and "tcd" or "cd")
			vim.cmd(command .. " " .. vim.fn.fnameescape(cwd))
		end)
	end
	if not ok then
		vim.notify(tostring(err), vim.log.levels.ERROR)
		return
	end
	local panel = require("differ.panel").current()
	if panel then
		local tab = vim.api.nvim_win_get_tabpage(panel.origin_win)
		vim.t[tab].dotfiles_differ_review = { root = git_root, mode = mode }
		vim.t[tab].dotfiles_differ_compact = compact ~= false
	end
end

function M.open_differ()
	open_review("Differ", open_differ_comparison)
end

local function toggle_differ_comparison()
	local review = vim.t.dotfiles_differ_review
	if not review then
		vim.notify("Open Differ with Space gh to toggle HEAD/main", vim.log.levels.WARN)
		return
	end
	local compact = vim.t.dotfiles_differ_compact
	require("differ").close()
	open_differ_comparison(review.root, review.mode == "main" and "HEAD" or "main", compact)
end

local function edit_differ_file()
	local view = require("differ").active_view()
	if not view then
		return
	end
	-- Diff rows contain deletions and metadata. Resolve through Differ's line map,
	-- including when gf is invoked from the old side of a split diff.
	local column = view:column_for("old")
	if not column or column.winid ~= vim.api.nvim_get_current_win() then
		column = view:column_for("new")
	end
	if not column or not vim.api.nvim_win_is_valid(column.winid) then
		return
	end
	local cursor = vim.api.nvim_win_get_cursor(column.winid)
	-- Split columns share aligned rows. Resolve against the new column so a
	-- replaced old line goes to its replacement, not the next unchanged line.
	local new_column = view:column_for("new")
	local line = require("differ.nav").file_line(new_column.map, cursor[1]) or 1
	local mapped = column.map.lines[cursor[1]]
	local col = mapped and mapped.new == line and cursor[2] or 0
	local path = view.model.root and (view.model.root .. "/" .. view.model.path)
	edit_review_file(vim.api.nvim_get_current_tabpage(), path, { line, col })
end

local function show_differ_help()
	local lines = {
		"Differ review",
		"",
		"B       Toggle HEAD/main comparison",
		"gf      Edit source in the previous tab (keep review open)",
		"[ / ]   Previous / next hunk",
		"[f / ]f Previous / next file",
		"Enter   Open selected file from the tree",
		"t       Toggle stacked / split layout",
		"T       Toggle compact / full context (default: compact)",
		"X       Discard hunk; in tree: WHOLE FILE (confirmation)",
		"        Uncommitted view only; changes actual files",
		"q       Close review and return to the editor",
		"",
		"R       Refresh file tree",
		"dd      Toggle file tree",
		"s / u   Stage / unstage hunk or file",
		"df      Edit beside an uncommitted diff",
	}
	local buf = vim.api.nvim_create_buf(false, true)
	vim.bo[buf].bufhidden = "wipe"
	vim.api.nvim_buf_set_lines(buf, 0, -1, false, lines)
	vim.bo[buf].modifiable = false
	-- Size against the terminal, not a narrow side-by-side diff column.
	local width, height = math.min(68, vim.o.columns - 4), math.min(#lines, vim.o.lines - 4)
	local win = vim.api.nvim_open_win(buf, true, {
		relative = "editor",
		style = "minimal",
		border = "rounded",
		width = width,
		height = height,
		row = math.floor((vim.o.lines - height) / 2) - 1,
		col = math.floor((vim.o.columns - width) / 2),
	})
	for _, key in ipairs({ "q", "<Esc>" }) do
		vim.keymap.set("n", key, function()
			vim.api.nvim_win_close(win, true)
		end, { buffer = buf })
	end
end

function M.setup_differ(opts)
	require("differ").setup(opts)
	local group = vim.api.nvim_create_augroup("dotfiles-differ-review", { clear = true })
	vim.api.nvim_create_autocmd({ "FileType", "BufEnter" }, {
		group = group,
		callback = function(args)
			local buf = args.buf
			if vim.bo[buf].filetype ~= "differdiff" and vim.bo[buf].filetype ~= "differpanel" then
				return
			end
			-- FileType fires before Differ finishes installing its own mappings.
			vim.schedule(function()
				if not vim.api.nvim_buf_is_valid(buf) then
					return
				end
				vim.keymap.set(
					"n",
					"B",
					toggle_differ_comparison,
					{ buffer = buf, desc = "Toggle HEAD/Main Comparison" }
				)
				vim.keymap.set("n", "gf", edit_differ_file, { buffer = buf, desc = "Edit File at Current Line" })
				vim.keymap.set("n", "g?", show_differ_help, { buffer = buf, desc = "Differ Review Help" })
				vim.keymap.set("n", "T", toggle_differ_context, { buffer = buf, desc = "Toggle Compact/Full Context" })
				if vim.bo[buf].filetype == "differdiff" and not watched_diffs[buf] then
					watched_diffs[buf] = vim.api.nvim_buf_attach(buf, false, {
						on_lines = function()
							schedule_differ_folds(buf)
						end,
						on_detach = function()
							watched_diffs[buf] = nil
						end,
					})
					schedule_differ_folds(buf)
				end
			end)
		end,
	})
end

return M
