local M = {}

local function assert_wait(msg, timeout, predicate)
	local ok = vim.wait(timeout, predicate, 50)
	assert(ok, msg)
	return predicate()
end

local function run_git(args, cwd)
	local result = vim.system(args, { cwd = cwd, text = true }):wait()
	assert(result.code == 0, string.format("command failed: %s\n%s", table.concat(args, " "), result.stderr or ""))
	return vim.trim(result.stdout or "")
end

local function write_file(path, lines)
	local parent = vim.fs.dirname(path)
	if parent and parent ~= "" then
		vim.fn.mkdir(parent, "p")
	end
	assert(vim.fn.writefile(lines, path) == 0, "failed to write " .. path)
end

local function create_temp_repo()
	local repo = vim.fn.tempname()
	assert(vim.fn.mkdir(repo, "p") == 1, "failed to create temp repo")

	write_file(repo .. "/nvim/init.lua", { "alpha", "baseline" })
	write_file(repo .. "/nested/beta.txt", { "beta", "baseline" })

	run_git({ "git", "init", "--initial-branch=main" }, repo)
	run_git({ "git", "config", "user.email", "tests@example.com" }, repo)
	run_git({ "git", "config", "user.name", "Diffview Picker Tests" }, repo)
	run_git({ "git", "add", "." }, repo)
	run_git({ "git", "commit", "-m", "baseline" }, repo)

	write_file(repo .. "/nvim/init.lua", { "alpha", "changed" })
	write_file(repo .. "/nested/beta.txt", { "beta", "changed" })

	return repo
end

local function assert_picker_items_match_view(picker, files)
	local items = picker:items()
	assert(#items == #files, "picker item count should match Diffview file count")

	for index, file in ipairs(files) do
		local item = items[index]
		assert(item ~= nil, string.format("missing picker item %d", index))
		assert(item.diffview_file == file, string.format("picker item %d should keep Diffview file identity", index))
		assert(item.path == file.path, string.format("picker item %d should use Diffview path", index))
	end

	return items
end

local function wait_for_diffview(selected_path)
	return assert_wait("Diffview view should open", 15000, function()
		local view = require("diffview.lib").get_current_view()
		if not (view and view.panel and view.panel.cur_file) then
			return nil
		end
		if selected_path and view.panel.cur_file.path ~= selected_path then
			return nil
		end
		return view
	end)
end

local function get_review_windows(view)
	local wins = {}
	for _, win in ipairs(view.cur_layout.windows or {}) do
		if win.id and vim.api.nvim_win_is_valid(win.id) then
			local bufnr = vim.api.nvim_win_get_buf(win.id)
			wins[#wins + 1] = {
				id = win.id,
				bufnr = bufnr,
				name = vim.api.nvim_buf_get_name(bufnr),
				winbar = vim.wo[win.id].winbar,
				lines = vim.api.nvim_buf_get_lines(bufnr, 0, 5, false),
			}
		end
	end
	return wins
end

local function assert_worktree_buffer_lines(view, expected_path, expected_lines)
	local worktree = assert_wait("Diffview working tree buffer should load", 15000, function()
		for _, win in ipairs(get_review_windows(view)) do
			if win.winbar == " WORKING TREE - " .. expected_path then
				return win
			end
		end
		return nil
	end)

	assert(worktree.name:sub(-#expected_path) == expected_path, "working tree buffer should point to selected file")
	assert(vim.deep_equal(worktree.lines, expected_lines), "working tree buffer should show live file content")
	return worktree
end

local function assert_picker_preview_ready(picker)
	return assert_wait("picker preview should render a diff", 5000, function()
		local preview = picker.preview
		if not (preview and preview.win and preview.win:valid() and preview.win.buf) then
			return nil
		end
		local lines = vim.api.nvim_buf_get_lines(preview.win.buf, 0, -1, false)
		if #lines == 0 then
			return nil
		end
		return lines
	end)
end

local function close_diffview()
	vim.cmd("DiffviewClose")
	assert_wait("Diffview should close", 5000, function()
		return require("diffview.lib").get_current_view() == nil
	end)
end

function M.run()
	local repo = create_temp_repo()
	vim.cmd("cd " .. vim.fn.fnameescape(repo))
	vim.cmd("edit " .. vim.fn.fnameescape(repo .. "/nvim/init.lua"))

	vim.cmd("DiffviewOpen main --selected-file=nvim/init.lua")
	local base_view = wait_for_diffview("nvim/init.lua")
	assert(#base_view.panel:ordered_file_list() == 2, "expected two changed files in base Diffview")
	assert_worktree_buffer_lines(base_view, "nvim/init.lua", { "alpha", "changed" })
	close_diffview()

	vim.cmd("DiffviewPicker")
	local outside_picker = assert_wait("Diffview picker should open outside Diffview", 5000, function()
		local current = Snacks.picker.get({ source = "diffview_picker" })[1]
		return current and #current:items() == 2 and current or nil
	end)

	assert(outside_picker.opts.preview == "diff", "outside picker should use diff preview")
	assert(outside_picker.opts.layout.preset == "vertical", "outside picker should use preview-visible layout")
	assert(outside_picker.preview and outside_picker.preview.win:valid(), "outside picker should expose a preview window")
	local outside_preview_lines = assert_picker_preview_ready(outside_picker)
	assert(#outside_preview_lines > 0, "outside picker preview should not be empty")

	local outside_items = outside_picker:items()
	local outside_target_index
	for index, item in ipairs(outside_items) do
		if item.path == "nested/beta.txt" then
			outside_target_index = index
			break
		end
	end

	assert(outside_target_index ~= nil, "outside picker should include nested/beta.txt")
	outside_picker.list:view(outside_target_index, 1)
	outside_picker:action("confirm")

	assert_wait("outside picker should close", 5000, function()
		return Snacks.picker.get({ source = "diffview_picker" })[1] == nil
	end)

	local outside_view = wait_for_diffview("nested/beta.txt")
	assert_worktree_buffer_lines(outside_view, "nested/beta.txt", { "beta", "changed" })
	close_diffview()

	vim.cmd("DiffviewOpen")
	local view = wait_for_diffview()
	local files = view.panel:ordered_file_list()
	assert(#files == 2, "expected two changed files in Diffview")

	local review_winid = view.cur_layout:get_main_win().id
	assert(vim.api.nvim_win_is_valid(review_winid), "Diffview review window should be valid")

	local non_main_winid
	if view.cur_layout and view.cur_layout.windows then
		for _, win in ipairs(view.cur_layout.windows) do
			if win.id ~= review_winid and vim.api.nvim_win_is_valid(win.id) then
				non_main_winid = win.id
				break
			end
		end
	end

	assert(non_main_winid ~= nil, "Diffview should expose a non-main review split")
	vim.api.nvim_set_current_win(non_main_winid)
	assert(vim.api.nvim_get_current_win() == non_main_winid, "test should launch picker from a non-main Diffview split")

	vim.cmd("DiffviewPicker")

	local picker = assert_wait("Diffview picker should open", 5000, function()
		local current = Snacks.picker.get({ source = "diffview_picker" })[1]
		return current and #current:items() == #files and current or nil
	end)

	assert(picker.opts.preview == "diff", "active Diffview picker should use diff preview")
	assert(picker.opts.layout.preset == "vertical", "active Diffview picker should keep preview visible")
	assert(picker.preview and picker.preview.win:valid(), "active Diffview picker should expose a preview window")
	local preview_lines = assert_picker_preview_ready(picker)
	assert(#preview_lines > 0, "active Diffview picker preview should not be empty")

	local items = assert_picker_items_match_view(picker, files)
	local target_index = items[1].diffview_file == view.panel.cur_file and 2 or 1
	local target_item = items[target_index]

	picker.list:view(target_index, 1)
	picker:action("confirm")

	assert_wait("Diffview picker should close", 5000, function()
		return Snacks.picker.get({ source = "diffview_picker" })[1] == nil
	end)

	assert_wait("Diffview selection should update and restore focus", 15000, function()
		return view.panel.cur_file == target_item.diffview_file and vim.api.nvim_get_current_win() == review_winid
	end)

	assert(view:infer_cur_file() == target_item.diffview_file, "Diffview should expose the selected file after confirm")
	assert(
		vim.api.nvim_buf_get_name(vim.api.nvim_win_get_buf(review_winid)) == target_item.diffview_file.absolute_path,
		"Diffview review buffer should show the selected file"
	)

	close_diffview()
end

return M
