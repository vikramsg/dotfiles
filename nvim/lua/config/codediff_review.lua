local M = {}

local function open_file(ctx, open_native)
	local session = require("codediff.ui.lifecycle").get_session(ctx.tabpage)
	if not session then
		return open_native(ctx)
	end
	local cursor = vim.api.nvim_win_get_cursor(0)
	local bufnr = vim.api.nvim_get_current_buf()
	local in_diff = bufnr == session.original_bufnr or bufnr == session.modified_bufnr
	local target_file = in_diff and (bufnr == session.original_bufnr and session.original or session.modified).absolute
	local source_lines = in_diff and vim.api.nvim_buf_get_lines(bufnr, 0, -1, false)
	open_native(ctx)
	if in_diff and vim.api.nvim_get_current_tabpage() ~= ctx.tabpage and vim.api.nvim_buf_get_name(0) == target_file then
		-- The source may be HEAD, the index, or another revision. Compare it
		-- directly with the opened working file, including any unstaged edits.
		if bufnr ~= vim.api.nvim_get_current_buf() then
			local target_lines = vim.api.nvim_buf_get_lines(0, 0, -1, false)
			local diff = require("codediff.core.diff").compute_diff(source_lines, target_lines, require("codediff.ui.view.render").diff_options())
			cursor[1] = require("codediff.ui.view.compact").compute_corresponding_lnum(diff.changes, "original", "modified", cursor[1])
		end
		vim.api.nvim_win_set_cursor(0, require("codediff.ui.view.cursor").clamp_cursor(vim.api.nvim_get_current_win(), cursor))
		vim.cmd("normal! zv")
	end
end

function M.toggle_comparison()
	local lifecycle = require("codediff.ui.lifecycle")
	local tabpage = vim.api.nvim_get_current_tabpage()
	local session = lifecycle.get_session(tabpage)
	if not session then
		return
	end
	local args = { "--repo", session.git_root }
	if not session.panel.view.data.base_revision then
		table.insert(args, "main")
	end
	if lifecycle.close(tabpage) then
		vim.cmd({ cmd = "CodeDiff", args = args })
	end
end

function M.setup()
	local lifecycle = require("codediff.ui.lifecycle")
	local group = vim.api.nvim_create_augroup("dotfiles-codediff-review", { clear = true })
	local panes = require("codediff.ui.view.actions.panes")
	local open_native = panes.open_in_prev_tab
	-- Keep CodeDiff's own gf mapping so refreshes and layout changes cannot
	-- replace our cursor correction with an older binding.
	panes.open_in_prev_tab = function(ctx)
		return open_file(ctx, open_native)
	end
	local function attach_toggle(tabpage)
		local session = lifecycle.get_session(tabpage)
		if session and session.panel and session.panel.name == "explorer" then
			lifecycle.set_tab_keymap(tabpage, "n", "B", M.toggle_comparison, {
				desc = "Toggle working-tree/main comparison",
			})
		end
	end
	vim.api.nvim_create_autocmd({ "BufEnter", "BufWinEnter" }, {
		group = group,
		callback = function(event)
			local tabpage = vim.api.nvim_get_current_tabpage()
			vim.schedule(function()
				if vim.api.nvim_tabpage_is_valid(tabpage) then
					attach_toggle(tabpage)
					local session = lifecycle.get_session(tabpage)
					local explorer = session and session.panel and session.panel.name == "explorer" and session.panel.view
					if explorer and explorer.bufnr == event.buf and vim.api.nvim_win_is_valid(explorer.winid)
						and vim.api.nvim_win_get_position(explorer.winid)[2] == 0 then
						-- The native side-panel layout sizes correctly on either side,
						-- but recreates the explorer on the left whenever it is shown.
						vim.api.nvim_win_call(explorer.winid, function()
							vim.cmd("wincmd L")
						end)
						require("codediff.ui.layout").arrange(tabpage)
					end
				end
			end)
		end,
	})
end

return M
