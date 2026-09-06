local M = {}

local attached = setmetatable({}, { __mode = "k" })

local function session_for_panel(panel)
	local local_review = require("config.differ_local_review")
	local tab = panel.winid and vim.api.nvim_win_get_tabpage(panel.winid) or vim.api.nvim_get_current_tabpage()
	local session = local_review.session_for_tab(tab)
	if session and session.root == panel.root then
		return local_review.owns_current_branch(session) and session or nil
	end
	local store = local_review.store
	local identity = panel.root and store.current_identity(panel.root)
	if not identity then
		return nil
	end
	local path = store.resolve_path(panel.root, identity)
	if not path then
		return nil
	end
	return {
		root = store.canonical_root(panel.root),
		identity = identity,
		path = path,
		existed = vim.fn.filereadable(path) == 1,
	}
end

local function append_output(panel)
	local session = session_for_panel(panel)
	if not (session and session.path and vim.fn.filereadable(session.path) == 1) then
		return
	end
	-- The storage key is a long hash; give the sidebar a readable logical name.
	local lines = { "", "Review output (1)", "  branch-review.json" }
	local meta = {
		{ kind = "review_output_blank" },
		{ kind = "review_output_header" },
		{ kind = "review_output", path = session.path },
	}
	vim.bo[panel.bufnr].modifiable = true
	vim.api.nvim_buf_set_lines(panel.bufnr, -1, -1, false, lines)
	vim.bo[panel.bufnr].modifiable = false
	vim.list_extend(panel.lines, lines)
	vim.list_extend(panel.meta, meta)
end

local function output_under_cursor(panel)
	if not (panel and panel.winid and vim.api.nvim_win_is_valid(panel.winid)) then
		return nil
	end
	local meta = panel.meta[vim.api.nvim_win_get_cursor(panel.winid)[1]]
	return meta and meta.kind == "review_output" and meta or nil
end

function M.open(path, panel)
	if vim.fn.filereadable(path) ~= 1 then
		return vim.notify("Differ local review: branch review has not been saved yet", vim.log.levels.WARN)
	end
	local origin = panel:content_win()
	vim.api.nvim_set_current_win(origin)
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

function M.select(panel)
	local output = output_under_cursor(panel)
	if output then
		return M.open(output.path, panel)
	end
	-- Differ's default Enter returns focus to the tree. Reviews intentionally land
	-- in the selected file, while directory rows still use select's native toggle.
	panel:select(true)
end

function M.attach(panel)
	if not panel or attached[panel] then
		return
	end
	attached[panel] = true
	local render = panel.render
	panel.render = function(self)
		render(self)
		append_output(self)
	end
	local on_refresh = panel.on_refresh
	panel.on_refresh = function(...)
		if on_refresh then
			on_refresh(...)
		end
		panel:render()
	end
	panel:render()
end

function M.refresh(root)
	local panel = require("differ.panel").current()
	if panel and panel.root and vim.fs.normalize(panel.root) == vim.fs.normalize(root) then
		M.attach(panel)
		panel:render()
	end
	for _, buf in ipairs(vim.api.nvim_list_bufs()) do
		if vim.api.nvim_buf_is_valid(buf) and vim.b[buf].dotfiles_differ_review_output then
			local path = vim.b[buf].dotfiles_differ_review_output
			if vim.fn.filereadable(path) == 1 then
				vim.bo[buf].modifiable = true
				vim.api.nvim_buf_set_lines(buf, 0, -1, false, vim.fn.readfile(path))
				vim.bo[buf].modifiable = false
			end
		end
	end
end

return M
