local M = {}

local function append_review_output(panel)
	local session = panel.dotfiles_local_review_session
	if not (session and session.path and vim.fn.filereadable(session.path) == 1) then
		return
	end
	local filename = vim.fn.fnamemodify(session.path, ":t")
	local lines = { "", "Review output (1)", "  .agents/reviews/", "    " .. filename }
	local meta = {
		{ kind = "review_output_blank" },
		{ kind = "review_output_header" },
		{ kind = "review_output_path" },
		{ kind = "review_output", path = session.path },
	}
	vim.bo[panel.bufnr].modifiable = true
	vim.api.nvim_buf_set_lines(panel.bufnr, -1, -1, false, lines)
	vim.bo[panel.bufnr].modifiable = false
	vim.list_extend(panel.lines, lines)
	vim.list_extend(panel.meta, meta)
end

local function review_output_under_cursor(panel)
	if not (panel and panel.winid and vim.api.nvim_win_is_valid(panel.winid)) then
		return
	end
	local meta = panel.meta[vim.api.nvim_win_get_cursor(panel.winid)[1]]
	return meta and meta.kind == "review_output" and meta or nil
end

local function open_review_output(path, panel)
	if vim.fn.filereadable(path) ~= 1 then
		return vim.notify("Differ local review: branch review has not been saved yet", vim.log.levels.WARN)
	end
	vim.api.nvim_set_current_win(panel:content_win())
	vim.cmd("belowright split")
	local win = vim.api.nvim_get_current_win()
	local buf = vim.api.nvim_create_buf(false, true)
	vim.api.nvim_win_set_buf(win, buf)
	vim.bo[buf].buftype = "nofile"
	vim.bo[buf].bufhidden = "wipe"
	vim.bo[buf].swapfile = false
	vim.bo[buf].filetype = "json"
	vim.api.nvim_buf_set_name(buf, "differ-review://" .. vim.fn.fnamemodify(path, ":t") .. "#" .. buf)
	vim.api.nvim_buf_set_lines(buf, 0, -1, false, vim.fn.readfile(path))
	vim.bo[buf].modifiable = false
	vim.bo[buf].readonly = true
	vim.b[buf].dotfiles_differ_review_output = path
	vim.keymap.set("n", "q", function()
		if vim.api.nvim_win_is_valid(win) then
			vim.api.nvim_win_close(win, true)
		end
	end, { buffer = buf, desc = "Close Review Output" })
end

local function select_panel_row(panel)
	local output = review_output_under_cursor(panel)
	if output then
		return open_review_output(output.path, panel)
	end
	panel:select(true)
end

function M.attach_review_panel(panel, session)
	if not panel then
		return
	end
	panel.dotfiles_local_review_session = session
	if not panel.dotfiles_review_output_attached then
		panel.dotfiles_review_output_attached = true
		local render = panel.render
		panel.render = function(self)
			render(self)
			append_review_output(self)
		end
		local on_refresh = panel.on_refresh
		panel.on_refresh = function(...)
			if on_refresh then
				on_refresh(...)
			end
			panel:render()
		end
	end
	panel:render()
	vim.keymap.set("n", "<CR>", function()
		select_panel_row(panel)
	end, { buffer = panel.bufnr, desc = "Open Review Item" })
end

function M.refresh_review_output(session)
	local panel = session and session.panel
	if panel and panel.dotfiles_local_review_session == session and panel:is_alive() then
		panel:render()
	end
	for _, buf in ipairs(vim.api.nvim_list_bufs()) do
		if vim.api.nvim_buf_is_valid(buf) and vim.b[buf].dotfiles_differ_review_output == session.path then
			vim.bo[buf].modifiable = true
			vim.api.nvim_buf_set_lines(buf, 0, -1, false, vim.fn.readfile(session.path))
			vim.bo[buf].modifiable = false
		end
	end
end

local function review_comparison()
	local git_root = Snacks.git.get_root()
	if not git_root then
		vim.notify("Differ requires a Git repository", vim.log.levels.ERROR)
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
		return git_root, "HEAD"
	end

	local against_main = vim.system({ "git", "diff", "--quiet", "main...HEAD", "--" }, {
		cwd = git_root,
		text = true,
	}):wait()
	if against_main.code == 1 then
		return git_root, "main"
	elseif against_main.code == 0 then
		vim.notify("No changes since HEAD or since branching from main", vim.log.levels.INFO)
	else
		vim.notify(against_main.stderr or "Unable to compare against main", vim.log.levels.ERROR)
	end
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

local function open_differ_comparison(git_root, mode, compact, local_session)
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
		local local_review = require("config.differ_local_review")
		local_session = local_session or local_review.new_session(git_root, mode)
		local_review.assign(tab, local_session, mode)
		local_session.panel = panel
		M.attach_review_panel(panel, local_session)
		vim.t[tab].dotfiles_differ_review = { root = git_root, mode = mode, local_session_id = local_session.id }
		vim.t[tab].dotfiles_differ_compact = compact ~= false
	end
end

function M.open_differ()
	local root, mode = review_comparison()
	if root then
		open_differ_comparison(root, mode)
	end
end

local function toggle_differ_comparison()
	local review = vim.t.dotfiles_differ_review
	if not review then
		vim.notify("Open Differ with Space gd to toggle HEAD/main", vim.log.levels.WARN)
		return
	end
	local compact = vim.t.dotfiles_differ_compact
	local local_review = require("config.differ_local_review")
	local local_session = local_review.session_for_tab()
	if not local_review.owns_current_branch(local_session) then
		vim.notify("Branch changed; close and reopen the Differ review", vim.log.levels.WARN)
		return
	end
	require("differ").close()
	open_differ_comparison(review.root, review.mode == "main" and "HEAD" or "main", compact, local_session)
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

-- PR sessions are global in Differ; never mistake a PR in another tab for the
-- local diff under the cursor. Check buffer ownership, not mere session presence.
local function current_pr()
	local session = require("differ.pr").current_session()
	local buf = vim.api.nvim_get_current_buf()
	if session then
		if session.panel and session.panel.bufnr == buf then
			return session
		end
		for _, col in ipairs((session.view and session.view.columns) or {}) do
			if col.bufnr == buf then
				return session
			end
		end
	end
end

local function list_prs()
	local session = current_pr()
	-- Land in the diff, where these buffer-local review controls are available.
	require("differ.pr").open({ land = "files", coords = session and session.coords })
end

local function start_pr_review()
	if current_pr() then
		return require("differ.pr").review()
	end
	local win, buf = vim.api.nvim_get_current_win(), vim.api.nvim_get_current_buf()
	vim.ui.input({ prompt = "PR number: " }, function(input)
		if not input or vim.trim(input) == "" then
			return
		end
		input = vim.trim(input)
		local number = tonumber(input)
		if not input:match("^%d+$") or not number or number < 1 or number > 2147483647 then
			vim.notify("Enter a positive PR number", vim.log.levels.WARN)
			return
		end
		-- A delayed prompt must not operate on a different editor/repository.
		if vim.api.nvim_get_current_win() ~= win or vim.api.nvim_win_get_buf(win) ~= buf then
			return
		end
		require("differ.pr").open({ number = number, land = "files", review = true })
	end)
end

local function show_differ_help()
	local pr = current_pr()
	local lines = {
		pr and "Differ PR review" or "Differ local review",
		"",
		"Space pl  List / open PRs",
		"Space pr  Start / resume GITHUB PR review (asks for PR if needed)",
	}
	if pr then
		local native_comment = require("differ").get_config().keymaps.diff.comment
		local native_label = type(native_comment) == "table" and table.concat(native_comment, ", ")
			or tostring(native_comment)
		vim.list_extend(lines, {
			"Space ps  Submit review: Comment / Approve / Request Changes",
			"c         Comment on line / visual selection → GITHUB",
			"" .. native_label .. "        Native GitHub comment key (also available)",
			"gp        Reply to thread (diff only)",
			"gx        Delete latest GitHub thread comment",
			"i         Type in composer if it opens in normal mode",
			"Ctrl+S (insert) or Esc then Enter  Save GitHub comment",
			"q (normal composer)  Cancel composer only",
			"Start a review first: saved comments become GitHub drafts.",
			"Without a pending review, comments may post immediately.",
			"Submit opens a summary editor; Esc then Enter submits it.",
		})
	else
		vim.list_extend(lines, {
			"Destination: LOCAL → persistent branch review JSON",
			"c       Add local note on line / visual selection (diff only)",
			"ge      Edit local note under cursor",
			"gx      Delete local note under cursor",
			"Space cr Copy saved branch-review JSON path",
			"Space cR Reset this branch review (confirmation)",
			"i       Type in composer if it opens in normal mode",
			"Ctrl+S (insert) or Esc then Enter  Save local note",
			"q (normal composer)  Cancel composer only",
			"B       Toggle HEAD/main comparison",
			"X       Discard hunk; in tree: WHOLE FILE (confirmation)",
			"        Uncommitted view only; changes actual files",
			"s / u   Stage / unstage hunk or file",
			"df      Edit beside an uncommitted diff",
		})
	end
	vim.list_extend(lines, {
		"",
		"gf      Edit source in the previous tab (keep review open)",
		"[ / ]   Previous / next hunk",
		"[f / ]f Previous / next file",
		"Enter   Open selected file and focus its diff; toggle directories",
		"        On Review output: open read-only JSON split (q closes it)",
		"t       Toggle stacked / split layout",
		"T       Toggle compact / full context (default: compact)",
		"q       Close review and return to the editor",
		"",
		"R       Refresh file tree",
		"dd      Toggle file tree",
	})
	-- Include the actual mappings too: Differ owns additional tree/thread controls,
	-- and its configured keys should remain discoverable through our custom help.
	vim.list_extend(lines, { "", "All buffer-local shortcuts (j/k to scroll):" })
	for _, mode in ipairs({ "n", "x" }) do
		local maps = vim.api.nvim_buf_get_keymap(0, mode)
		table.sort(maps, function(a, b)
			return a.lhs < b.lhs
		end)
		for _, map in ipairs(maps) do
			if map.desc then
				local key = map.lhs:gsub("^ ", "Space ")
				lines[#lines + 1] = string.format("%s%s  %s", key, mode == "x" and " (visual)" or "", map.desc)
			end
		end
	end
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

local function label_github_composer()
	if vim.bo.filetype == "markdown" then
		local winbar = vim.wo.winbar
		if not winbar:find("GITHUB", 1, true) then
			vim.wo.winbar = "GITHUB → pull request · " .. winbar
		end
	end
end

local function github_comment()
	require("differ.pr").comment()
	label_github_composer()
end

local function github_comment_range()
	require("differ.pr").comment_range()
	label_github_composer()
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
				vim.keymap.set("n", "<leader>pl", list_prs, { buffer = buf, desc = "List/Open PRs" })
				vim.keymap.set("n", "<leader>pr", start_pr_review, { buffer = buf, desc = "Start/Resume PR Review" })
				if vim.bo[buf].filetype == "differpanel" then
					local pr = require("differ.pr").current_session()
					local panel = pr and pr.panel and pr.panel.bufnr == buf and pr.panel
						or require("differ.panel").current()
					if panel and panel.bufnr == buf then
						vim.keymap.set("n", "<CR>", function()
							select_panel_row(panel)
						end, { buffer = buf, desc = "Open Review Item" })
					end
				end
				local review = vim.t.dotfiles_differ_review
				local local_review = require("config.differ_local_review")
				local session = local_review.session_for_tab()
				if review and session and not current_pr() then
					vim.keymap.set("n", "<leader>cr", local_review.copy_review_path, {
						buffer = buf,
						desc = "Copy Branch Review JSON Path",
					})
					vim.keymap.set("n", "<leader>cR", local_review.reset, {
						buffer = buf,
						desc = "Reset Branch Review",
					})
				end
				if vim.bo[buf].filetype == "differdiff" then
					local pr = current_pr()
					if pr then
						-- c is an explicit alias; Differ's configurable native key remains bound.
						vim.keymap.set("n", "c", github_comment, { buffer = buf, desc = "Comment on GitHub PR" })
						vim.keymap.set(
							"x",
							"c",
							github_comment_range,
							{ buffer = buf, desc = "Comment on GitHub PR Range" }
						)
					else
						if review and session then
							local_review.attach(session, require("differ").active_view())
							vim.keymap.set(
								"n",
								"c",
								local_review.comment,
								{ buffer = buf, desc = "Add Local Review Note" }
							)
							vim.keymap.set(
								"x",
								"c",
								local_review.comment_range,
								{ buffer = buf, desc = "Add Local Review Range Note" }
							)
							vim.keymap.set(
								"n",
								"ge",
								local_review.edit,
								{ buffer = buf, desc = "Edit Local Review Note" }
							)
							vim.keymap.set(
								"n",
								"gx",
								local_review.delete,
								{ buffer = buf, desc = "Delete Local Review Note" }
							)
						end
					end
				end
				-- Submit, native comment/reply, and composer controls stay native to Differ's PR UI.
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
