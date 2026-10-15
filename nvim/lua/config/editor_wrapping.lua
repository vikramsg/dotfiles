local M = {}

local function enable_editor_wrapping()
	local win = vim.api.nvim_get_current_win()
	local buf = vim.api.nvim_win_get_buf(win)
	if vim.api.nvim_win_get_config(win).relative ~= "" or vim.bo[buf].buftype ~= "" or vim.wo[win].diff then
		return
	end

	-- The working file can also be visible in a normal editor window. Only
	-- CodeDiff's panes need to retain its unwrapped scroll alignment.
	local lifecycle = package.loaded["codediff.ui.lifecycle"]
	local session = lifecycle and lifecycle.get_session(vim.api.nvim_win_get_tabpage(win))
	if session and (win == session.original_win or win == session.modified_win or win == session.result_win) then
		return
	end

	vim.wo[win].wrap = true
end

function M.setup()
	local group = vim.api.nvim_create_augroup("dotfiles-editor-wrapping", { clear = true })
	vim.api.nvim_create_autocmd({ "BufWinEnter", "WinEnter" }, {
		group = group,
		callback = enable_editor_wrapping,
	})
	enable_editor_wrapping()
end

return M
