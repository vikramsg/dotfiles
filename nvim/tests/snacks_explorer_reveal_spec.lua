local M = {}

local function assert_wait(msg, timeout, predicate)
	local ok = vim.wait(timeout, predicate, 50)
	assert(ok, msg)
	return predicate()
end

local function run_command(args, cwd)
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

	write_file(repo .. "/.gitignore", {
		"ignored/",
		".hidden_ignored/",
	})
	write_file(repo .. "/.hidden_visible/visible.txt", { "hidden visible" })
	write_file(repo .. "/ignored/plain.txt", { "ignored plain" })
	write_file(repo .. "/.hidden_ignored/secret.txt", { "hidden ignored" })

	run_command({ "git", "init", "--initial-branch=main" }, repo)
	return repo
end

local function close_explorer()
	for _, picker in ipairs(Snacks.picker.get({ source = "explorer" })) do
		picker:close()
	end
	assert_wait("Snacks Explorer should close", 5000, function()
		return Snacks.picker.get({ source = "explorer" })[1] == nil
	end)
	vim.wait(100, function()
		return false
	end, 10)
end

local function get_reveal_mapping_callback()
	local mapping = vim.fn.maparg("<leader>E", "n", false, true)
	assert(type(mapping.callback) == "function", "<leader>E should be a Lua callback")
	return mapping.callback
end

local function invoke_reveal_mapping()
	get_reveal_mapping_callback()()
end

local function wait_for_revealed_file(target)
	target = vim.fs.normalize(target)
	return assert_wait("Snacks Explorer should reveal " .. target, 10000, function()
		local picker = Snacks.picker.get({ source = "explorer" })[1]
		if not picker then
			return nil
		end

		local current = picker:current()
		if current and current.file and vim.fs.normalize(current.file) == target then
			return picker
		end
		return nil
	end)
end

local function edit_file(path)
	vim.cmd("edit " .. vim.fn.fnameescape(path))
	assert(vim.fs.normalize(vim.api.nvim_buf_get_name(0)) == vim.fs.normalize(path), "test should edit target file")
end

local function open_existing_explorer(repo, opts)
	local file_win = vim.api.nvim_get_current_win()
	Snacks.explorer(vim.tbl_extend("force", { cwd = repo, hidden = false, ignored = false }, opts or {}))
	local picker = assert_wait("Snacks Explorer should open", 5000, function()
		return Snacks.picker.get({ source = "explorer" })[1]
	end)
	assert(vim.api.nvim_win_is_valid(file_win), "file window should remain valid")
	vim.api.nvim_set_current_win(file_win)
	return picker
end

local function assert_reveals(target, expected)
	edit_file(target)
	invoke_reveal_mapping()
	local picker = wait_for_revealed_file(target)

	if expected.hidden ~= nil then
		assert(picker.opts.hidden == expected.hidden, "unexpected explorer hidden option")
	end
	if expected.ignored ~= nil then
		assert(picker.opts.ignored == expected.ignored, "unexpected explorer ignored option")
	end
	if expected.init_hidden ~= nil then
		assert(picker.init_opts and picker.init_opts.hidden == expected.init_hidden, "unexpected init hidden option")
	end
	if expected.init_ignored ~= nil then
		assert(picker.init_opts and picker.init_opts.ignored == expected.init_ignored, "unexpected init ignored option")
	end

	return picker
end

function M.run()
	local repo = create_temp_repo()
	local hidden_visible = repo .. "/.hidden_visible/visible.txt"
	local ignored_plain = repo .. "/ignored/plain.txt"
	local hidden_ignored = repo .. "/.hidden_ignored/secret.txt"

	vim.cmd("cd " .. vim.fn.fnameescape(repo))
	close_explorer()

	assert_reveals(hidden_visible, { hidden = true, ignored = false })
	close_explorer()

	assert_reveals(ignored_plain, { hidden = false, ignored = true })
	close_explorer()

	edit_file(ignored_plain)
	local existing = open_existing_explorer(repo, { hidden = false, ignored = false })
	assert(existing.opts.hidden == false, "precondition: existing explorer should hide hidden files")
	assert(existing.opts.ignored == false, "precondition: existing explorer should hide ignored files")
	assert_reveals(ignored_plain, { hidden = false, ignored = true, init_ignored = true })
	close_explorer()

	edit_file(hidden_ignored)
	existing = open_existing_explorer(repo, { hidden = true, ignored = false })
	assert(existing.opts.hidden == true, "precondition: existing explorer should show hidden files")
	assert(existing.opts.ignored == false, "precondition: existing explorer should hide ignored files")
	assert_reveals(hidden_ignored, { hidden = true, ignored = true, init_hidden = true, init_ignored = true })
	close_explorer()

	vim.fn.delete(repo, "rf")
end

return M
