local M = {}

local function wait_for(message, predicate)
	assert(vim.wait(10000, predicate, 25), message)
end

local function git(root, ...)
	local args = { "git", "-C", root, "-c", "user.name=CodeDiff Test", "-c", "user.email=codediff@test.invalid" }
	vim.list_extend(args, { ... })
	local result = vim.system(args, { text = true }):wait()
	assert(result.code == 0, result.stderr)
	return result.stdout
end

local function write(root, path, lines)
	assert(vim.fn.writefile(lines, root .. "/" .. path) == 0)
end

local function tab_text(tabpage)
	local lines = {}
	for _, win in ipairs(vim.api.nvim_tabpage_list_wins(tabpage)) do
		vim.list_extend(lines, vim.api.nvim_buf_get_lines(vim.api.nvim_win_get_buf(win), 0, -1, false))
	end
	return table.concat(lines, "\n")
end

local function active_session()
	return require("codediff.ui.lifecycle.session").get_active_diffs()[vim.api.nvim_get_current_tabpage()]
end

local function comparison()
	local session = active_session()
	local refs = session and session.panel.view.data.source_revisions
	return refs and refs.original
end

local function press(text)
	vim.api.nvim_feedkeys(vim.api.nvim_replace_termcodes(text, true, false, true), "mx", false)
end

local function select_explorer_file(tabpage, filename)
	for _, win in ipairs(vim.api.nvim_tabpage_list_wins(tabpage)) do
		local bufnr = vim.api.nvim_win_get_buf(win)
		if vim.bo[bufnr].filetype == "codediff-explorer" then
			for row, line in ipairs(vim.api.nvim_buf_get_lines(bufnr, 0, -1, false)) do
				if line:find(filename, 1, true) then
					vim.api.nvim_set_current_win(win)
					vim.api.nvim_win_set_cursor(win, { row, 0 })
					press("<CR>")
					return true
				end
			end
		end
	end
	return false
end

function M.run()
	require("lazy").load({ plugins = { "codediff.nvim" } })
	local root = vim.fn.tempname()
	assert(vim.fn.mkdir(root, "p") == 1)
	local other_root = vim.fn.tempname()
	assert(vim.fn.mkdir(other_root, "p") == 1)
	local original_cwd = vim.fn.getcwd()
	local original_hidden = vim.o.hidden
	local original_tab = vim.api.nvim_get_current_tabpage()
	local tabs_before = {}
	for _, tab in ipairs(vim.api.nvim_list_tabpages()) do
		tabs_before[tab] = true
	end

	local ok, err = xpcall(function()
		git(root, "init", "--initial-branch=main")
		write(root, "base.txt", { "base" })
		local context_lines = {}
		for index = 1, 40 do
			context_lines[index] = "context " .. index
		end
		write(root, "context.txt", context_lines)
		git(root, "add", ".")
		git(root, "commit", "-m", "base")
		git(root, "switch", "-c", "feature")
		write(root, "branch-only.txt", { "committed branch change" })
		git(root, "add", ".")
		git(root, "commit", "-m", "branch change")
		write(root, "working-only.txt", { "uncommitted change" })
		write(root, "aaa-untracked.txt", { "first explorer preview" })
		write(root, "base.txt", { "working hunk" })
		context_lines[20] = "changed context line"
		table.insert(context_lines, 10, "inserted context line")
		write(root, "context.txt", context_lines)
		git(other_root, "init", "--initial-branch=main")
		write(other_root, "other-repo.txt", { "different repository" })
		git(other_root, "add", ".")
		git(other_root, "commit", "-m", "other repository")

		vim.cmd("cd " .. vim.fn.fnameescape(root))
		press("<Space>gd")
		wait_for("Space gd should open CodeDiff", function()
			return active_session() ~= nil
		end)
		local working_tab = vim.api.nvim_get_current_tabpage()
		assert(active_session().git_root == root, "native CodeDiff should review the fixture repository: " .. tostring(active_session().git_root))
		assert(comparison() == nil, "Space gd should start in native repository-status mode")
		wait_for("the first explorer preview should be an untracked file", function()
			return active_session().single_pane and active_session().modified.relative == "aaa-untracked.txt"
		end)
		wait_for("reviews should start in compact mode", function()
			return active_session().compact_mode == true
		end)
		local panel_win = active_session().panel.view.winid
		local panel_col = vim.api.nvim_win_get_position(panel_win)[2]
		for _, diff_win in ipairs({ active_session().original_win, active_session().modified_win }) do
			assert(vim.api.nvim_win_get_position(diff_win)[2] < panel_col, "CodeDiff explorer should be to the right of the diff panes")
		end
		wait_for("working-tree view should show the uncommitted file", function()
			return tab_text(working_tab):find("working%-only%.txt") ~= nil
		end)
		local lifecycle = require("codediff.ui.lifecycle")
		local close = lifecycle.close
		lifecycle.close = function()
			return false
		end
		require("config.codediff_review").toggle_comparison()
		lifecycle.close = close
		assert(active_session() and comparison() == nil, "cancelled close must keep the current review")
		assert(vim.o.mouse:find("a", 1, true), "mouse input should be enabled for explorer clicks")
		local explorer_mouse_mapping
		for _, win in ipairs(vim.api.nvim_tabpage_list_wins(working_tab)) do
			local bufnr = vim.api.nvim_win_get_buf(win)
			if vim.bo[bufnr].filetype == "codediff-explorer" then
				explorer_mouse_mapping = vim.api.nvim_buf_call(bufnr, function()
					return vim.fn.maparg("<2-LeftMouse>", "n", false, true)
				end)
			end
		end
		assert(explorer_mouse_mapping and explorer_mouse_mapping.lhs, "double-click should open the selected file diff")
		assert(select_explorer_file(working_tab, "working-only.txt"), "explorer should open an untracked file before a tracked diff")
		wait_for("untracked file should finish loading", function()
			return active_session().single_pane and active_session().modified.relative == "working-only.txt"
		end)
		assert(select_explorer_file(working_tab, "context.txt"), "explorer should contain the context test file")
		local session = active_session()
		local compact_ready = vim.wait(10000, function()
			return session.modified.relative == "context.txt"
				and session.compact_mode == true
				and session.modified_bufnr
				and vim.api.nvim_buf_line_count(session.modified_bufnr) == 41
				and session.stored_diff_result and #session.stored_diff_result.changes > 0
				and vim.wo[session.modified_win].foldmethod == "expr"
				and vim.wo[session.modified_win].foldenable
		end, 25)
		assert(compact_ready, "selected context file should load with compact folds: " .. vim.inspect({
			relative = session.modified.relative,
			compact = session.compact_mode,
			applied = session.compact_default_applied,
			modified_buffer = session.modified_bufnr,
			modified_lines = session.modified_bufnr and vim.api.nvim_buf_line_count(session.modified_bufnr),
			foldmethod = session.modified_win and vim.wo[session.modified_win].foldmethod,
			foldenable = session.modified_win and vim.wo[session.modified_win].foldenable,
			changes = session.stored_diff_result and session.stored_diff_result.changes,
		}))
		assert(vim.api.nvim_get_current_win() == session.modified_win, "Enter should focus the diff pane")
		local first_fold = vim.api.nvim_win_call(session.modified_win, function()
			return vim.fn.foldclosed(1)
		end)
		assert(first_fold == 1, "compact mode should fold unchanged lines before the changed hunk: " .. vim.inspect({
			fold = first_fold,
			foldlevel = vim.wo[session.modified_win].foldlevel,
			foldexpr = vim.wo[session.modified_win].foldexpr,
			modified_lines = vim.api.nvim_buf_get_lines(session.modified_bufnr, 0, -1, false),
			changes = session.stored_diff_result.changes,
		}))
		vim.api.nvim_win_set_cursor(session.modified_win, { 21, 4 })
		press("gf")
		assert(vim.api.nvim_get_current_tabpage() ~= working_tab, "gf should return to an editor tab")
		assert(vim.api.nvim_buf_get_name(0) == root .. "/context.txt", "gf should open the real changed file")
		assert(vim.deep_equal(vim.api.nvim_win_get_cursor(0), { 21, 4 }), "gf should preserve the diff cursor line and column")
		assert(vim.fn.foldclosed(21) == -1, "gf should reveal the destination line")
		assert(vim.api.nvim_get_current_buf() == session.modified_bufnr, "normal editing should reuse the working-file diff buffer")
		assert(vim.wo.wrap, "a normal view of the working-file diff buffer should wrap")
		vim.wo.foldmethod = "manual"
		vim.cmd("20,25fold")
		vim.api.nvim_set_current_tabpage(working_tab)
		vim.api.nvim_set_current_win(session.original_win)
		assert(not vim.wo[session.original_win].wrap and not vim.wo[session.modified_win].wrap, "CodeDiff views of the shared file should stay unwrapped")
		wait_for("gf should resume in the original diff pane", function()
			return vim.fn.maparg("gf", "n", false, true).desc == "Open buffer in previous tab"
		end)
		vim.api.nvim_win_set_cursor(session.original_win, { 20, 4 })
		press("gf")
		assert(vim.api.nvim_buf_get_name(0) == root .. "/context.txt", "old-side gf should open the real changed file")
		assert(vim.deep_equal(vim.api.nvim_win_get_cursor(0), { 21, 4 }), "old-side gf should translate past inserted lines")
		assert(vim.fn.foldclosed(21) == -1, "gf should open an existing editor fold around the destination")
		vim.api.nvim_set_current_tabpage(working_tab)
		vim.api.nvim_set_current_win(session.modified_win)
		wait_for("review mappings should resume after returning from gf", function()
			return vim.fn.maparg("gc", "n", false, true).desc == "Toggle compact mode"
		end)
		press("gc")
		assert(session.compact_mode == false, "gc should disable compact mode")
		for _, win in ipairs({ session.original_win, session.modified_win }) do
			assert(vim.api.nvim_win_call(win, function()
				return vim.fn.foldclosed(1)
			end) == -1, "gc should visibly unfold unchanged lines in both diff panes")
		end
		assert(select_explorer_file(working_tab, "base.txt"), "explorer should contain the modified tracked file")
		session = active_session()
		wait_for("selected file should open in the diff pane", function()
			return session.modified.relative == "base.txt"
				and session.modified_win
				and vim.api.nvim_win_is_valid(session.modified_win)
				and session.original_bufnr and vim.api.nvim_buf_is_valid(session.original_bufnr)
				and session.modified_bufnr and vim.api.nvim_buf_is_valid(session.modified_bufnr)
				and vim.api.nvim_buf_get_lines(session.original_bufnr, 0, -1, false)[1] == "base"
				and vim.api.nvim_buf_get_lines(session.modified_bufnr, 0, -1, false)[1] == "working hunk"
		end)
		wait_for("Enter should focus the diff pane", function()
			return vim.api.nvim_get_current_win() == session.modified_win
		end)
		assert(session.compact_mode == false, "selecting another file should preserve gc toggle-off")
		vim.api.nvim_set_current_win(session.modified_win)
		local function mapping(key)
			return vim.api.nvim_buf_call(vim.api.nvim_get_current_buf(), function()
				return vim.fn.maparg(key, "n", false, true).lhs
			end)
		end
		assert(mapping("]") == "]" and mapping("[") == "[", "hunk navigation should use ] and [")
		assert(mapping("X") == "X", "X should be mapped to discard a hunk in the file diff")
		local confirm = vim.fn.confirm
		vim.fn.confirm = function()
			return 1
		end
		vim.api.nvim_win_set_cursor(session.modified_win, { 1, 0 })
		press("X")
		vim.fn.confirm = confirm
		local discarded = vim.wait(5000, function()
			local lines = vim.fn.readfile(root .. "/base.txt")
			return #lines == 1 and lines[1] == "base"
		end, 25)
		assert(discarded, "X should discard the selected hunk from the working file: " .. table.concat(vim.fn.readfile(root .. "/base.txt"), "\n"))
		wait_for("review toggle should remain mapped after discarding a hunk", function()
			return mapping("B") == "B"
		end)

		vim.cmd("cd " .. vim.fn.fnameescape(other_root))
		press("B")
		wait_for("B should switch to branch mode", function()
			return active_session() ~= nil and comparison() == "main"
		end)
		local branch_tab = vim.api.nvim_get_current_tabpage()
		assert(active_session().git_root == root, "mode toggle should retain the review repository")
		wait_for("branch review should include committed branch changes", function()
			return tab_text(branch_tab):find("branch%-only%.txt") ~= nil
		end)

		press("B")
		wait_for("B should switch back to working-tree mode", function()
			return active_session() ~= nil and comparison() == nil
		end)
		local returned_tab = vim.api.nvim_get_current_tabpage()
		wait_for("working-tree review should exclude committed branch-only files", function()
			local text = tab_text(returned_tab)
			return text:find("working%-only%.txt") ~= nil and text:find("branch%-only%.txt") == nil
		end)

		assert(select_explorer_file(returned_tab, "working-only.txt"), "explorer should contain the uncommitted file")
		session = active_session()
		wait_for("selecting a file should open its diff", function()
			return session.modified_win and vim.api.nvim_win_is_valid(session.modified_win)
		end)
		vim.api.nvim_set_current_win(session.modified_win)
		assert(vim.fn.maparg("B", "n", false, true).lhs == "B", "B should be mapped in the selected diff buffer")
		press("t")
		press("B")
		wait_for("B should still toggle after file selection and layout change", function()
			return active_session() ~= nil and comparison() == "main"
		end)
		local layout_branch_tab = vim.api.nvim_get_current_tabpage()
		wait_for("branch review after layout change should show committed changes", function()
			return tab_text(layout_branch_tab):find("branch%-only%.txt") ~= nil
		end)

		assert(lifecycle.close(layout_branch_tab), "test branch review should close")
		git(root, "add", "working-only.txt", "aaa-untracked.txt", "context.txt")
		git(root, "commit", "-m", "save working change")
		vim.cmd("cd " .. vim.fn.fnameescape(root))
		press("<Space>gd")
		vim.wait(300)
		assert(active_session() == nil, "clean Space gd should not silently open a branch review")
		vim.cmd({ cmd = "CodeDiff", args = { "main", "--repo", root } })
		wait_for("a direct CodeDiff command should retain its requested comparison", function()
			return active_session() ~= nil and comparison() == "main"
		end)
		assert(lifecycle.close(vim.api.nvim_get_current_tabpage()), "clean-tree branch review should close")
		git(root, "switch", "main")
		write(root, "base.txt", { "main working change" })
		vim.cmd("cd " .. vim.fn.fnameescape(root))
		press("<Space>gd")
		wait_for("dirty main branch should open working-tree mode", function()
			return active_session() ~= nil and comparison() == nil
		end)
		press("B")
		wait_for("main branch comparison should be classified as branch mode when merge-base is HEAD", function()
			return active_session() ~= nil and comparison() == "main"
		end)
		press("B")
		wait_for("B should return from the main branch comparison to working-tree mode", function()
			return active_session() ~= nil and comparison() == nil
		end)

		assert(lifecycle.close(vim.api.nvim_get_current_tabpage()), "working review should close before staged review")
		local staged_lines = {}
		for index = 1, 40 do
			staged_lines[index] = "context " .. index
		end
		table.insert(staged_lines, 5, "staged insertion")
		write(root, "context.txt", staged_lines)
		git(root, "add", "context.txt")
		table.insert(staged_lines, 10, "unstaged insertion")
		write(root, "context.txt", staged_lines)
		vim.cmd({ cmd = "CodeDiff", args = { "--staged", "--repo", root } })
		wait_for("native staged review should load index contents", function()
			local staged = active_session()
			return staged and staged.modified_revision == ":0" and staged.stored_diff_result and staged.stored_diff_result.changes
		end)
		local staged_tab = vim.api.nvim_get_current_tabpage()
		session = active_session()
		local explorer = session.panel.view
		vim.api.nvim_set_current_win(session.modified_win)
		press("<Space>b")
		assert(explorer.is_hidden, "native explorer toggle should hide the panel")
		press("<Space>b")
		wait_for("reshown explorer should remain on the right", function()
			return not explorer.is_hidden and vim.api.nvim_win_get_position(explorer.winid)[2] > vim.api.nvim_win_get_position(session.modified_win)[2]
		end)
		press("t")
		press("t")
		wait_for("native layout rebuild should finish", function()
			return session.layout == "side-by-side" and session.original_win and vim.api.nvim_win_is_valid(session.original_win)
				and session.modified_revision == ":0" and session.stored_diff_result and session.stored_diff_result.changes
		end)
		for _, source in ipairs({ { "original", 20 }, { "modified", 21 } }) do
			local win = session[source[1] .. "_win"]
			vim.api.nvim_set_current_win(win)
			wait_for("gf mapping should be available after native rebuild", function()
				return vim.fn.maparg("gf", "n", false, true).callback ~= nil
			end)
			vim.api.nvim_win_set_cursor(win, { source[2], 4 })
			press("gf")
			assert(vim.api.nvim_get_current_tabpage() ~= staged_tab, "staged gf should open an editor tab")
			assert(vim.api.nvim_buf_get_name(0) == root .. "/context.txt", "staged gf should open the working file")
			assert(vim.deep_equal(vim.api.nvim_win_get_cursor(0), { 22, 4 }), "staged gf should account for both staged and unstaged insertions")
			assert(vim.fn.foldclosed(22) == -1, "staged gf should reveal the working-file destination")
			assert(vim.wo.wrap, "opening a review file in the normal editor should enable wrapping")
			vim.api.nvim_set_current_tabpage(staged_tab)
			assert(not vim.wo[session.original_win].wrap and not vim.wo[session.modified_win].wrap, "returning to CodeDiff should keep both diff panes unwrapped")
		end
		vim.api.nvim_set_current_win(session.modified_win)
		wait_for("gf should resume before preparing the blocked editor", function()
			return vim.fn.maparg("gf", "n", false, true).callback ~= nil
		end)
		press("gf")
		assert(vim.api.nvim_get_current_tabpage() ~= staged_tab, "blocked-open setup should start in the editor")
		vim.cmd("edit " .. vim.fn.fnameescape(other_root .. "/other-repo.txt"))
		local dirty_buffer = vim.api.nvim_get_current_buf()
		local dirty_lines = {}
		for index = 1, 10 do
			dirty_lines[index] = "unsaved editor line " .. index
		end
		vim.api.nvim_buf_set_lines(dirty_buffer, 0, -1, false, dirty_lines)
		vim.wo.foldmethod = "manual"
		vim.cmd("2,5fold")
		vim.api.nvim_win_set_cursor(0, { 8, 1 })
		vim.o.hidden = false
		vim.api.nvim_set_current_tabpage(staged_tab)
		vim.api.nvim_set_current_win(session.original_win)
		wait_for("review mapping should resume before a blocked open", function()
			return vim.fn.maparg("gf", "n", false, true).callback ~= nil
		end)
		vim.api.nvim_win_set_cursor(0, { 20, 4 })
		press("gf")
		assert(vim.api.nvim_get_current_buf() == dirty_buffer, "a blocked edit should retain the unsaved editor buffer")
		assert(vim.deep_equal(vim.api.nvim_win_get_cursor(0), { 8, 1 }), "a failed gf must not move the unrelated editor cursor")
		assert(vim.fn.foldclosed(2) == 2, "a failed gf must not unfold the unrelated editor buffer")
		assert(vim.bo.modified and vim.deep_equal(vim.api.nvim_buf_get_lines(0, 0, -1, false), dirty_lines), "a failed gf must preserve unsaved editor contents")
		vim.bo.modified = false
	end, debug.traceback)

	vim.o.hidden = original_hidden
	for _, tab in ipairs(vim.api.nvim_list_tabpages()) do
		if not tabs_before[tab] then
			pcall(vim.api.nvim_set_current_tabpage, tab)
			pcall(function()
				require("codediff.ui.lifecycle").close(tab)
			end)
			if vim.api.nvim_tabpage_is_valid(tab) then
				pcall(vim.api.nvim_tabpage_close, tab, true)
			end
		end
	end
	vim.api.nvim_set_current_tabpage(original_tab)
	vim.cmd("cd " .. vim.fn.fnameescape(original_cwd))
	vim.fn.delete(root, "rf")
	vim.fn.delete(other_root, "rf")
	assert(ok, err)
	print("CodeDiff review: working-tree default and B comparison toggle passed")
end

return M
