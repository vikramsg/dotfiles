local M = {}

function M.run()
	local original_tab = vim.api.nvim_get_current_tabpage()
	vim.cmd("tabnew")
	local tab = vim.api.nvim_get_current_tabpage()
	local editor = vim.api.nvim_get_current_win()
	local file = vim.api.nvim_get_current_buf()
	local scratch = vim.api.nvim_create_buf(false, true)
	local floating
	local ok, err = xpcall(function()
		vim.wo[editor].wrap = false
		vim.cmd("vsplit")
		local other_editor = vim.api.nvim_get_current_win()
		assert(vim.wo[other_editor].wrap, "a normal split should wrap even when inherited options disabled wrapping")
		vim.api.nvim_set_current_win(editor)
		assert(vim.wo[editor].wrap, "entering an ordinary file window should restore wrapping")

		vim.api.nvim_win_set_buf(editor, scratch)
		vim.wo[editor].wrap = false
		vim.api.nvim_set_current_win(other_editor)
		vim.api.nvim_set_current_win(editor)
		assert(not vim.wo[editor].wrap, "entering a plugin scratch window must preserve its wrapping setting")
		vim.api.nvim_win_set_buf(editor, file)
		assert(vim.wo[editor].wrap, "showing an ordinary file in a reused window should restore wrapping")

		floating = vim.api.nvim_open_win(file, true, {
			relative = "editor", row = 1, col = 1, width = 30, height = 4,
		})
		vim.wo[floating].wrap = false
		vim.api.nvim_set_current_win(editor)
		vim.api.nvim_set_current_win(floating)
		assert(not vim.wo[floating].wrap, "a floating view of the same file should retain its own wrapping setting")
		vim.api.nvim_win_close(floating, true)

		vim.api.nvim_set_current_win(editor)
		vim.cmd("diffthis")
		vim.api.nvim_set_current_win(other_editor)
		vim.api.nvim_set_current_win(editor)
		assert(not vim.wo[editor].wrap, "native diff windows should retain their diff wrapping behavior")
		vim.cmd("diffoff")
	end, debug.traceback)

	vim.api.nvim_set_current_tabpage(tab)
	vim.cmd("tabclose!")
	vim.api.nvim_set_current_tabpage(original_tab)
	vim.api.nvim_buf_delete(scratch, { force = true })
	assert(ok, err)
end

return M
