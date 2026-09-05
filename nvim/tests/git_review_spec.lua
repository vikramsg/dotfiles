-- Exercise real Git repositories and plugin views through the configured keys.
-- Assertions concern visible files, source positions, and preserved editor state.
local M = {}

local function wait_for(message, predicate)
	assert(vim.wait(5000, predicate, 20), message)
end

local function keys(text)
	vim.v.errmsg = ""
	vim.api.nvim_feedkeys(vim.api.nvim_replace_termcodes(text, true, false, true), "mx", false)
	assert(vim.v.errmsg == "", vim.v.errmsg)
end

local function git(root, ...)
	local args = { "git", "-C", root, "-c", "user.name=Review Test", "-c", "user.email=review@test.invalid" }
	vim.list_extend(args, { ... })
	local result = vim.system(args, { text = true }):wait()
	assert(result.code == 0, result.stderr)
	return result.stdout
end

local function write(root, path, lines)
	assert(vim.fn.writefile(lines, root .. "/" .. path) == 0)
end

local function tab_text()
	local lines = {}
	for _, win in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
		vim.list_extend(lines, vim.api.nvim_buf_get_lines(vim.api.nvim_win_get_buf(win), 0, -1, false))
	end
	return table.concat(lines, "\n")
end

local function contains(text)
	return tab_text():find(text, 1, true) ~= nil
end

local function focus_text(text, filetype)
	local found
	wait_for("review should display " .. text, function()
		for _, win in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
			local buf = vim.api.nvim_win_get_buf(win)
			if not filetype or vim.bo[buf].filetype == filetype then
				for row, line in ipairs(vim.api.nvim_buf_get_lines(buf, 0, -1, false)) do
					if line:find(text, 1, true) then
						found = { win, row }
						return true
					end
				end
			end
		end
	end)
	vim.api.nvim_set_current_win(found[1])
	vim.api.nvim_win_set_cursor(found[1], { found[2], 0 })
	return found[1], found[2]
end

local function ready_maps()
	wait_for("custom review keys should be available", function()
		return vim.fn.maparg("B", "n") ~= "" and vim.fn.maparg("gf", "n") ~= ""
	end)
end

local function with_fixture(test)
	local root = vim.fn.tempname()
	vim.fn.mkdir(root, "p")
	root = vim.fn.resolve(root)
	local initial_tab = vim.api.nvim_get_current_tabpage()
	local cwd = vim.fn.getcwd()
	local old_tabs = {}
	for _, tab in ipairs(vim.api.nvim_list_tabpages()) do
		old_tabs[tab] = true
	end
	local old_buffers = {}
	for _, buf in ipairs(vim.api.nvim_list_bufs()) do
		old_buffers[buf] = true
	end
	local notify = vim.notify
	local confirm = vim.fn.confirm
	local notices = {}
	vim.notify = function(message)
		notices[#notices + 1] = tostring(message)
	end
	local ok, err = xpcall(function()
		git(root, "init", "--initial-branch=main")
		local original = { "start", "removed one", "removed two", "target before" }
		for i = 5, 30 do
			original[i] = "context " .. i
		end
		write(root, "example.txt", original)
		write(root, "branch.txt", { "base" })
		write(root, "other.txt", { "other before" })
		git(root, "add", ".")
		git(root, "commit", "-m", "initial")
		git(root, "checkout", "-b", "review-test")
		write(root, "branch.txt", { "committed branch change" })
		git(root, "add", "branch.txt")
		git(root, "commit", "-m", "branch change")
		-- Main advances independently: branch comparisons must use the merge base.
		git(root, "checkout", "main")
		write(root, "main-only.txt", { "not part of this branch" })
		git(root, "add", "main-only.txt")
		git(root, "commit", "-m", "main advances")
		git(root, "checkout", "review-test")
		vim.cmd("tabnew")
		local editor_tab = vim.api.nvim_get_current_tabpage()
		vim.cmd("cd " .. vim.fn.fnameescape(root))
		vim.cmd("edit " .. vim.fn.fnameescape(root .. "/example.txt"))
		local editor_win = vim.api.nvim_get_current_win()
		vim.cmd("vnew")
		local scratch_win, scratch_buf = vim.api.nvim_get_current_win(), vim.api.nvim_get_current_buf()
		test({
			root = root,
			original = original,
			editor_tab = editor_tab,
			editor_win = editor_win,
			scratch_win = scratch_win,
			scratch_buf = scratch_buf,
			notices = notices,
		})
	end, debug.traceback)
	if package.loaded["differ"] then
		pcall(require("differ").close)
	end
	for _, tab in ipairs(vim.api.nvim_list_tabpages()) do
		if not old_tabs[tab] then
			if package.loaded["codediff.ui.lifecycle"] then
				pcall(require("codediff.ui.lifecycle").close, tab)
			end
			if vim.api.nvim_tabpage_is_valid(tab) then
				vim.api.nvim_set_current_tabpage(tab)
				vim.cmd("tabclose!")
			end
		end
	end
	vim.api.nvim_set_current_tabpage(initial_tab)
	vim.cmd("cd " .. vim.fn.fnameescape(cwd))
	for _, buf in ipairs(vim.api.nvim_list_bufs()) do
		if not old_buffers[buf] then
			pcall(vim.api.nvim_buf_delete, buf, { force = true })
		end
	end
	vim.notify = notify
	vim.fn.confirm = confirm
	vim.fn.delete(root, "rf")
	assert(ok, err)
end

local function dirty(f)
	local changed = { "start", "target after" }
	for i = 5, 30 do
		changed[#changed + 1] = i == 25 and "second changed hunk" or "context " .. i
	end
	write(f.root, "example.txt", changed)
	write(f.root, "other.txt", { "other after" })
	write(f.root, "new file.txt", { "new untracked content" })
end

local function close_review(f)
	keys("q")
	wait_for("q should return to the editor tab", function()
		return vim.api.nvim_get_current_tabpage() == f.editor_tab
	end)
	assert(vim.api.nvim_win_get_buf(f.scratch_win) == f.scratch_buf, "review must not replace the scratch split")
end

local function selection(shortcut, panel_type)
	with_fixture(function(f)
		dirty(f)
		keys(shortcut)
		wait_for("dirty review should include untracked files", function()
			return contains("new file.txt")
		end)
		assert(not contains("branch.txt"), "dirty review should exclude committed-only files")
		focus_text("example.txt", panel_type)
		ready_maps()
		keys("B")
		wait_for("B should include committed branch changes", function()
			return contains("branch.txt")
		end)
		assert(contains("new file.txt"), "branch total should retain untracked files")
		assert(not contains("main-only.txt"), "branch comparison should exclude changes made only on main")
		focus_text("branch.txt", panel_type)
		ready_maps()
		keys("B")
		wait_for("B should return to uncommitted changes", function()
			return contains("new file.txt") and not contains("branch.txt")
		end)
		focus_text("example.txt", panel_type)
		close_review(f)
		-- With a clean working tree, opening should automatically select branch changes.
		git(f.root, "add", ".")
		git(f.root, "commit", "-m", "save working changes")
		keys(shortcut)
		wait_for("clean review should include branch changes", function()
			return contains("branch.txt")
		end)
		assert(not contains("main-only.txt"), "clean comparison should use the merge base")
		focus_text("branch.txt", panel_type)
		close_review(f)
	end)
end

local function differ_editing()
	with_fixture(function(f)
		dirty(f)
		-- Exercise a local cwd; opening/closing must preserve its scope and value.
		vim.cmd("lcd " .. vim.fn.fnameescape(f.root))
		keys(" gh")
		focus_text("example.txt", "differpanel")
		keys("<CR>")
		focus_text("target after", "differdiff")
		ready_maps()
		local review_tab = vim.api.nvim_get_current_tabpage()
		keys("]")
		assert(vim.api.nvim_win_get_cursor(0)[1] > 10, "] should advance to the later hunk")
		keys("[")
		assert(vim.api.nvim_win_get_cursor(0)[1] < 10, "[ should return to the first hunk")
		focus_text("target after", "differdiff")
		local row = vim.api.nvim_win_get_cursor(0)[1]
		assert(row ~= 2, "fixture must distinguish a diff row from the source line")
		vim.api.nvim_win_set_cursor(0, { row, 4 })
		keys("gf")
		assert(vim.api.nvim_get_current_tabpage() == f.editor_tab, "gf should return to the previous tab")
		assert(vim.api.nvim_get_current_win() == f.editor_win, "gf should reuse the file's editor split")
		assert(vim.deep_equal(vim.api.nvim_win_get_cursor(0), { 2, 4 }), "gf should map the source line and column")
		assert(vim.api.nvim_win_get_buf(f.scratch_win) == f.scratch_buf, "gf should preserve scratch buffers")
		assert(vim.api.nvim_tabpage_is_valid(review_tab), "gf should leave the review open")
		assert(
			vim.fn.getcwd(f.scratch_win) == f.root and vim.fn.haslocaldir(f.scratch_win) == 1,
			"review should preserve local cwd"
		)
		vim.api.nvim_set_current_tabpage(review_tab)
		focus_text("target after", "differdiff")
		keys("t")
		focus_text("target before", "differdiff")
		ready_maps()
		keys("gf")
		assert(vim.api.nvim_get_current_win() == f.editor_win, "split-side gf should reuse the editor")
		assert(vim.api.nvim_win_get_cursor(0)[1] == 2, "old-side gf should resolve the new source line")
		vim.api.nvim_set_current_tabpage(review_tab)
		focus_text("target after", "differdiff")
		keys("]f")
		wait_for("]f should change files without leaving the diff", function()
			return vim.bo.filetype == "differdiff" and (contains("other after") or contains("new untracked content"))
		end)
		keys("[f")
		focus_text("target after", "differdiff")
		ready_maps()
		local diff_win = vim.api.nvim_get_current_win()
		keys("g?")
		wait_for("help should include our comparison and editing keys", function()
			return contains("Toggle HEAD/main") and contains("Edit source in the previous tab")
		end)
		keys("<Esc>")
		assert(vim.api.nvim_get_current_win() == diff_win, "Escape should dismiss help and restore the diff")
		focus_text("example.txt", "differpanel")
		close_review(f)
	end)
end

local function empty_and_errors(shortcut)
	with_fixture(function(f)
		git(f.root, "checkout", "main")
		keys(shortcut)
		assert(vim.api.nvim_get_current_tabpage() == f.editor_tab, "no changes should not open a review")
		assert(table.concat(f.notices):find("No changes since HEAD", 1, true), "empty review should explain why")
		git(f.root, "branch", "-m", "trunk")
		local notice_count = #f.notices
		keys(shortcut)
		assert(vim.api.nvim_get_current_tabpage() == f.editor_tab, "missing main should not open a review")
		assert(
			#f.notices > notice_count and f.notices[#f.notices]:find("main", 1, true),
			"missing main should produce a diagnostic"
		)
		-- A dirty repository does not require a main branch.
		write(f.root, "new file.txt", { "only untracked" })
		keys(shortcut)
		wait_for("untracked-only review should open without main", function()
			return contains("new file.txt")
		end)
		ready_maps()
		close_review(f)
		vim.api.nvim_set_current_win(f.scratch_win)
		vim.cmd("lcd " .. vim.fn.fnameescape(vim.fs.dirname(f.root)))
		keys(shortcut)
		assert(vim.api.nvim_get_current_tabpage() == f.editor_tab, "outside Git should not open a review")
		assert(
			f.notices[#f.notices]:find("requires a Git repository", 1, true),
			"outside Git should produce a diagnostic"
		)
	end)
end

-- Inspect native fold visibility, not just buffer text (folded text stays loaded).
local function expect_context(compact, message, columns)
	local state = {}
	local ok = vim.wait(5000, function()
		state = {}
		local count = 0
		for _, win in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
			local buf = vim.api.nvim_win_get_buf(win)
			if vim.bo[buf].filetype == "differdiff" then
				count = count + 1
				local folded = vim.api.nvim_win_call(win, function()
					for row, line in ipairs(vim.api.nvim_buf_get_lines(buf, 0, -1, false)) do
						if line == "context 15" then
							return vim.fn.foldclosed(row) ~= -1
						end
					end
				end)
				state[#state + 1] = { win = win, folded = folded, file = vim.api.nvim_buf_get_name(buf) }
				if folded ~= compact then
					return false
				end
			end
		end
		return count == (columns or 1)
	end, 20)
	assert(ok, message .. ": " .. vim.inspect(state))
end

local function differ_context()
	with_fixture(function(f)
		write(f.root, "other.txt", f.original)
		git(f.root, "add", "other.txt")
		git(f.root, "commit", "-m", "add context to second file")
		dirty(f)
		local other = vim.deepcopy(f.original)
		other[4], other[25] = "other after", "other second hunk"
		write(f.root, "other.txt", other)
		keys(" gh")
		focus_text("target after", "differdiff")
		expect_context(true, "reviews should start compact")
		-- Exactly three unchanged lines adjacent to a hunk remain visible.
		for row, line in ipairs(vim.api.nvim_buf_get_lines(0, 0, -1, false)) do
			if line == "context 7" or line == "context 22" then
				assert(vim.fn.foldclosed(row) == -1, "three surrounding context lines should remain visible")
			elseif line == "context 8" or line == "context 21" then
				assert(vim.fn.foldclosed(row) ~= -1, "context beyond three lines should be folded")
			end
		end
		local cursor = vim.api.nvim_win_get_cursor(0)
		keys("T")
		expect_context(false, "T should expand unchanged regions")
		assert(vim.deep_equal(cursor, vim.api.nvim_win_get_cursor(0)), "T should keep the changed-line cursor")
		keys("]f")
		focus_text("other after", "differdiff")
		expect_context(false, "full context should survive file switching")
		keys("t")
		expect_context(false, "full context should survive layout switching", 2)
		ready_maps()
		keys("T")
		expect_context(true, "T should compact both split columns", 2)
		keys("[f")
		focus_text("target after", "differdiff")
		expect_context(true, "compact context should survive file switching", 2)
		keys("t")
		expect_context(true, "compact context should survive layout switching")
		focus_text("example.txt", "differpanel")
		ready_maps()
		keys("T")
		expect_context(false, "T should work from the file tree")
		keys("B")
		focus_text("example.txt", "differpanel")
		keys("<CR>")
		focus_text("target after", "differdiff")
		expect_context(false, "full context should survive comparison switching")
		ready_maps()
		keys("T")
		expect_context(true, "branch review should also compact")
		keys("B")
		focus_text("target after", "differdiff")
		expect_context(true, "compact context should survive comparison switching")
		focus_text("example.txt", "differpanel")
		keys("R")
		expect_context(true, "refresh should keep compact context")
		ready_maps()
		keys("g?")
		assert(contains("Toggle compact / full") and contains("WHOLE FILE"), "help should explain T and X's scope")
		keys("<Esc>")
		close_review(f)
	end)
end

local function differ_discard()
	with_fixture(function(f)
		dirty(f)
		local before = vim.fn.readfile(f.root .. "/example.txt")
		local index = git(f.root, "write-tree")
		keys(" gh")
		focus_text("target after", "differdiff")
		expect_context(true, "discard fixture should start compact")
		local prompt
		vim.fn.confirm = function(message, _, default)
			prompt = message
			assert(default == 2, "discard confirmation should default to No")
			return 2
		end
		keys("X")
		assert(prompt and prompt:find("Revert hunk", 1, true), "X should request hunk confirmation")
		assert(vim.deep_equal(before, vim.fn.readfile(f.root .. "/example.txt")), "cancel must preserve every change")
		vim.fn.confirm = function()
			return 1
		end
		keys("X")
		local expected = vim.deepcopy(f.original)
		expected[25] = "second changed hunk"
		assert(
			vim.deep_equal(expected, vim.fn.readfile(f.root .. "/example.txt")),
			"X should revert only the selected hunk"
		)
		assert(git(f.root, "write-tree") == index, "discarding an unstaged hunk must not change the index")
		assert(vim.fn.readfile(f.root .. "/other.txt")[1] == "other after", "discard must preserve other files")
		expect_context(true, "discard rerender should retain compact context")
		focus_text("second changed hunk", "differdiff")
		keys("T")
		expect_context(false, "full context should still work after discard")
		close_review(f)
	end)
end

local function staged_and_deleted()
	with_fixture(function(f)
		dirty(f)
		git(f.root, "add", "example.txt")
		vim.fn.delete(f.root .. "/other.txt")
		keys(" gh")
		wait_for("review should include staged changes", function()
			return contains("Staged")
		end)
		focus_text("example.txt", "differpanel")
		keys("<CR>")
		focus_text("target after", "differdiff")
		ready_maps()
		local tab = vim.api.nvim_get_current_tabpage()
		keys("gf")
		assert(vim.api.nvim_get_current_win() == f.editor_win, "staged-file gf should reuse the source split")
		assert(vim.api.nvim_win_get_cursor(0)[1] == 2, "staged-file gf should open the mapped line")
		assert(
			git(f.root, "diff", "--cached", "--name-only"):find("example.txt", 1, true),
			"gf must not unstage the file"
		)
		vim.api.nvim_set_current_tabpage(tab)
		focus_text("other.txt", "differpanel")
		keys("<CR>")
		focus_text("other before", "differdiff")
		ready_maps()
		keys("gf")
		assert(vim.api.nvim_get_current_tabpage() == tab, "deleted-file gf should stay in the review")
		assert(table.concat(f.notices):find("No editable working file", 1, true), "deleted-file gf should explain why")
		close_review(f)
	end)
end

function M.run()
	selection(" gd", "codediff-explorer")
	selection(" gh", "differpanel")
	differ_editing()
	differ_context()
	differ_discard()
	staged_and_deleted()
	empty_and_errors(" gd")
	empty_and_errors(" gh")
	print("Git review: comparison selection, switching, editing, navigation, help, and empty/error cases passed")
end

return M
