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

	write_file(repo .. "/alpha.txt", { "alpha", "baseline" })
	write_file(repo .. "/nested/beta.txt", { "beta", "baseline" })

	run_git({ "git", "init", "--initial-branch=main" }, repo)
	run_git({ "git", "config", "user.email", "tests@example.com" }, repo)
	run_git({ "git", "config", "user.name", "Diffview Picker Tests" }, repo)
	run_git({ "git", "add", "." }, repo)
	run_git({ "git", "commit", "-m", "baseline" }, repo)

	write_file(repo .. "/alpha.txt", { "alpha", "changed" })
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

function M.run()
	local repo = create_temp_repo()
	vim.cmd("cd " .. vim.fn.fnameescape(repo))
	vim.cmd("DiffviewOpen")

	local view = assert_wait("Diffview view should open", 15000, function()
		local lib = require("diffview.lib")
		local current = lib.get_current_view()
		return current and current.panel and current.panel.cur_file and #current.panel:ordered_file_list() == 2 and current or nil
	end)

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

	vim.cmd("DiffviewClose")
	assert_wait("Diffview should close", 5000, function()
		return require("diffview.lib").get_current_view() == nil
	end)
end

return M
