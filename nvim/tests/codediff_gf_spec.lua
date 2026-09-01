-- Characterizes the custom CodeDiff `gf` behavior in a previous tab with two
-- splits. The file is already open in one split while an unnamed scratch split
-- is focused; `gf` must reuse and focus the file split, preserve the diff
-- cursor, and leave the scratch split unchanged.
local M = {}

local function assert_wait(message, predicate)
	local ok = vim.wait(5000, predicate, 25)
	assert(ok, message)
	return predicate()
end

local function run_command(args, cwd)
	local result = vim.system(args, { cwd = cwd, text = true }):wait()
	assert(result.code == 0, string.format("command failed: %s\n%s", table.concat(args, " "), result.stderr or ""))
end

local function normalize(path)
	return vim.fs.normalize(vim.fn.fnamemodify(path, ":p"))
end

function M.run()
	local repo = vim.fn.tempname()
	local target = repo .. "/example.txt"
	local initial_tab = vim.api.nvim_get_current_tabpage()
	local fixture_tab
	local diff_tab
	local fixture_buffers = {}

	local ok, err = xpcall(function()
		assert(vim.fn.mkdir(repo, "p") == 1, "failed to create temporary repository")
		assert(vim.fn.writefile({ "one", "two", "three", "four" }, target) == 0, "failed to create test file")
		run_command({ "git", "init", "--initial-branch=main" }, repo)
		run_command({ "git", "add", "example.txt" }, repo)
		run_command({ "git", "-c", "user.name=CodeDiff Test", "-c", "user.email=codediff@test.invalid", "commit", "-m", "initial" }, repo)
		assert(vim.fn.writefile({ "one", "two", "three changed", "four" }, target) == 0, "failed to modify test file")

		vim.cmd("tabnew")
		fixture_tab = vim.api.nvim_get_current_tabpage()
		vim.cmd("edit " .. vim.fn.fnameescape(target))
		local file_win = vim.api.nvim_get_current_win()
		fixture_buffers[#fixture_buffers + 1] = vim.api.nvim_get_current_buf()

		vim.cmd("vnew")
		local scratch_win = vim.api.nvim_get_current_win()
		local scratch_buf = vim.api.nvim_get_current_buf()
		fixture_buffers[#fixture_buffers + 1] = scratch_buf
		assert(vim.api.nvim_get_current_win() == scratch_win, "scratch split should be focused before opening CodeDiff")

		vim.cmd("cd " .. vim.fn.fnameescape(repo))
		vim.cmd("CodeDiff --repo " .. vim.fn.fnameescape(repo))

		local lifecycle = require("codediff.ui.lifecycle")
		local observed = {}
		local function selected_modified_window()
			for _, tabpage in ipairs(vim.api.nvim_list_tabpages()) do
				if tabpage ~= fixture_tab and lifecycle.get_session(tabpage) then
					diff_tab = tabpage
					break
				end
			end
			if not diff_tab then
				return nil
			end
			local _, modified = lifecycle.get_paths(diff_tab)
			local _, win = lifecycle.get_windows(diff_tab)
			observed.path = modified and modified.absolute or nil
			observed.win = win
			if modified and normalize(modified.absolute) == normalize(target) and win and vim.api.nvim_win_is_valid(win) then
				return win
			end
		end
		local ready = vim.wait(5000, selected_modified_window, 25)
		assert(ready, "CodeDiff should open the modified file\n" .. vim.inspect(observed))
		local modified_win = selected_modified_window()

		vim.api.nvim_set_current_win(modified_win)
		local mapping = assert_wait("CodeDiff should install the custom gf mapping", function()
			local current = vim.fn.maparg("gf", "n", false, true)
			if type(current.callback) == "function" and current.desc == "Edit File at Current Line" then
				return current
			end
		end)

		vim.api.nvim_win_set_cursor(modified_win, { 3, 4 })
		mapping.callback()

		assert(vim.api.nvim_get_current_tabpage() == fixture_tab, "gf should return to the previous tab")
		assert(vim.api.nvim_get_current_win() == file_win, "gf should focus the split already showing the target file")
		assert(normalize(vim.api.nvim_buf_get_name(0)) == normalize(target), "gf should open the working-tree file")
		assert(vim.deep_equal(vim.api.nvim_win_get_cursor(0), { 3, 4 }), "gf should preserve the cursor position")
		assert(vim.api.nvim_win_get_buf(scratch_win) == scratch_buf, "gf should not replace the focused scratch split")
	end, debug.traceback)

	if diff_tab and vim.api.nvim_tabpage_is_valid(diff_tab) then
		pcall(require("codediff.ui.lifecycle").close, diff_tab)
	end
	if fixture_tab and vim.api.nvim_tabpage_is_valid(fixture_tab) then
		vim.api.nvim_set_current_tabpage(fixture_tab)
		vim.cmd("tabclose!")
	end
	if vim.api.nvim_tabpage_is_valid(initial_tab) then
		vim.api.nvim_set_current_tabpage(initial_tab)
	end
	for _, bufnr in ipairs(fixture_buffers) do
		if vim.api.nvim_buf_is_valid(bufnr) then
			pcall(vim.api.nvim_buf_delete, bufnr, { force = true })
		end
	end
	vim.fn.delete(repo, "rf")

	if not ok then
		error(err)
	end
end

return M
