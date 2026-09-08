-- Source-coordinate invariants, not color snapshots or keyboard walkthroughs.
local M = {}

local function model(path, old, new)
	return require("differ.model.diff").build({
		path = path,
		root = "/tmp/opencode/syntax-invariants",
		old_rev = "HEAD",
		new_rev = "WORKTREE",
		old_text = table.concat(old, "\n") .. "\n",
		new_text = table.concat(new, "\n") .. "\n",
	})
end

local function signature(row, start, finish, highlight)
	return table.concat({ row, start, finish, highlight }, ":")
end

local function actual_marks(buf, first, last)
	local result = {}
	-- Inspect prepared source ownership. The decoration provider's colors and
	-- viewport rendering are checked manually in Herdr, not via UI snapshots.
	for _, mark in ipairs(require("differ.syntax").get_marks(buf, first, last)) do
		result[signature(mark.row, mark.col_start, mark.col_end, mark.hl)] = true
	end
	return result
end

local function expected_marks(section)
	local marks = require("differ.syntax").collect({ side = "unified", map = section.map }, section.model)
	local expected = {}
	for _, mark in ipairs(marks) do
		expected[signature(section.body_first - 1 + mark.row, mark.col_start, mark.col_end, mark.hl)] = true
	end
	assert(next(expected), "the installed language parser must produce syntax captures")
	return expected
end

local function await_projection(view, section)
	local expected = expected_marks(section)
	assert(
		vim.wait(10000, function()
			return vim.deep_equal(expected, actual_marks(view.bufnr, section.body_first - 1, section.last))
		end, 10),
		"aggregate syntax must equal native source-derived syntax at the section's translated rows"
	)
end

local function stale_native_syntax()
	local syntax, render = require("differ.syntax"), require("differ.render")
	local collect_async, callbacks = syntax.collect_async, {}
	local buf = vim.api.nvim_create_buf(false, true)
	local ok, err = xpcall(function()
		local empty_done = false
		syntax.paint_async(buf, {}, {
			on_done = function()
				empty_done = true
			end,
		})
		assert(
			vim.wait(5000, function()
				return empty_done
			end, 10),
			"an empty syntax result must complete without painting"
		)
		syntax.collect_async = function(column, source, callback)
			callbacks[#callbacks + 1] = function()
				callback(syntax.collect(column, source))
			end
		end
		local old = model("late.lua", { "return 1" }, { "return 'old source'" })
		local latest = model("late.lua", { "return 1" }, { "local result = false", "return result" })
		local opts = { layout = "stacked", context = 3, deep_diff = require("differ").get_config().deep_diff }
		local old_column, new_column = render.render(old, opts).columns[1], render.render(latest, opts).columns[1]
		vim.api.nvim_buf_set_lines(buf, 0, -1, false, old_column.lines)
		syntax.apply(buf, old_column, old)
		vim.api.nvim_buf_set_lines(buf, 0, -1, false, new_column.lines)
		syntax.apply(buf, new_column, latest)
		callbacks[2]()
		local expected = expected_marks({ map = new_column.map, model = latest, body_first = 1 })
		assert(
			vim.wait(5000, function()
				return vim.deep_equal(expected, actual_marks(buf, 0, #new_column.lines))
			end, 10),
			"current source highlighting should complete"
		)
		callbacks[1]()
		assert(
			vim.deep_equal(expected, actual_marks(buf, 0, #new_column.lines)),
			"late source captures must not overwrite a newer native view"
		)
	end, debug.traceback)
	syntax.collect_async = collect_async
	vim.api.nvim_buf_delete(buf, { force = true })
	assert(ok, err)
end

function M.run()
	vim.v.errmsg = ""
	require("lazy").load({ plugins = { "differ.nvim" } })
	local syntax = require("differ.syntax")
	local first = {
		key = "first.lua",
		entry = { path = "first.lua" },
		model = model("first.lua", { "local text = [[", "old_value = true", "]]", "return text" }, {
			"local text = 'new'",
			"local new_value = false",
			"return text",
		}),
	}
	local second = {
		key = "second.py",
		entry = { path = "second.py" },
		model = model("second.py", { 'text = """', "old_value = True", '"""', "print(text)" }, {
			'text = "new"',
			"new_value = False",
			"print(text)",
		}),
	}
	local tab = vim.api.nvim_get_current_tabpage()
	vim.cmd("tabnew")
	local test_tab = vim.api.nvim_get_current_tabpage()
	local view
	local ok, err = xpcall(function()
		view = require("config.differ_continuous").View
			.new({
				winid = vim.api.nvim_get_current_win(),
				sections = { first, second },
			})
			:open()
		await_projection(view, first)
		await_projection(view, second)

		-- The old line looks like code, but belongs to a multiline Lua string.
		-- Its capture must come from the original source tree, not the mixed diff.
		local old_row = first.map.from_old[2] - 1
		local string_capture = false
		for _, capture in ipairs(syntax.collect({ side = "unified", map = first.map }, first.model)) do
			if capture.row == old_row and capture.hl:match("^@string") then
				string_capture = true
			end
		end
		assert(string_capture, "deleted multiline-string content must retain source-language context")

		local second_map = second.map
		local updated = model("first.lua", { "local text = [[", "old_value = true", "]]", "return text" }, {
			"local text = 'updated'",
			"local added = 12",
			"local new_value = false",
			"return text",
		})
		view:set_model(first, updated)
		assert(
			vim.wait(10000, function()
				return first.map.from_new[4] ~= nil
			end, 10),
			"changed section should grow"
		)
		await_projection(view, first)
		await_projection(view, second)
		assert(second.map == second_map, "syntax updates must not rebuild an unrelated file's line map")
		local before = actual_marks(view.bufnr, second.body_first - 1, second.last)
		view:jump_section(first)
		view:jump_section(second)
		assert(
			vim.deep_equal(before, actual_marks(view.bufnr, second.body_first - 1, second.last)),
			"navigation must retain another file's syntax"
		)
	end, debug.traceback)
	if view then
		view:close()
	end
	if vim.api.nvim_tabpage_is_valid(test_tab) then
		vim.api.nvim_set_current_tabpage(test_tab)
		vim.cmd("tabclose!")
	end
	vim.api.nvim_set_current_tabpage(tab)
	assert(ok, err)
	stale_native_syntax()
	assert(vim.v.errmsg == "", "syntax work must not report asynchronous errors: " .. vim.v.errmsg)
	print("Continuous syntax: native source projection, language context, and section update isolation passed")
end

return M
