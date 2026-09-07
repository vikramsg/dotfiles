-- Behavior at the changeset-view boundary. Visual styling and keyboard workflows
-- are exercised manually in Herdr, rather than duplicated as UI scripts here.
local M = {}

local function model(path, old, new)
	return require("differ.model.diff").build({
		path = path,
		root = "/tmp/opencode/continuous-model-test",
		old_rev = "HEAD",
		new_rev = "WORKTREE",
		old_text = table.concat(old, "\n") .. "\n",
		new_text = table.concat(new, "\n") .. "\n",
	})
end

local function section(path, old, new)
	return {
		key = path,
		entry = { path = path, additions = 1, deletions = 1 },
		model = model(path, old, new),
	}
end

local function wait(message, predicate)
	assert(vim.wait(5000, predicate, 10), message)
end

local function pending_open_ownership()
	local system, root, notify = vim.system, Snacks.git.get_root, vim.notify
	local callbacks, requests = {}, 0
	local original_buf = vim.api.nvim_get_current_buf()
	local other_buf = vim.api.nvim_create_buf(false, true)
	local function flush()
		local finished = false
		vim.schedule(function()
			finished = true
		end)
		wait("scheduled selection result should settle", function()
			return finished
		end)
	end
	local ok, err = xpcall(function()
		Snacks.git.get_root = function()
			return "/tmp/opencode"
		end
		vim.notify = function() end
		vim.system = function(command, _, callback)
			requests = requests + 1
			assert(command[2] == "status" and callback, "only asynchronous selection may run for a stale invocation")
			callbacks[#callbacks + 1] = callback
			return { kill = function() end }
		end
		local review = require("config.git_review")
		review.open_differ()
		vim.api.nvim_win_set_buf(0, other_buf)
		callbacks[1]({ code = 0, stdout = " M changed.txt\n" })
		flush()
		assert(
			requests == 1 and vim.api.nvim_get_current_buf() == other_buf,
			"a selection result must not replace a different editor buffer"
		)
		vim.api.nvim_win_set_buf(0, original_buf)
		review.open_differ()
		review.open_differ()
		callbacks[2]({ code = 0, stdout = " M changed.txt\n" })
		flush()
		assert(
			requests == 3 and vim.api.nvim_get_current_buf() == original_buf,
			"an older open must not supersede a newer request"
		)
		callbacks[3]({ code = 1, stderr = "fixture selection stopped" })
		flush()
	end, debug.traceback)
	vim.system, Snacks.git.get_root, vim.notify = system, root, notify
	vim.api.nvim_win_set_buf(0, original_buf)
	vim.api.nvim_buf_delete(other_buf, { force = true })
	assert(ok, err)
end

function M.run()
	vim.v.errmsg = ""
	require("lazy").load({ plugins = { "differ.nvim" } })
	local Continuous = require("config.differ_continuous")
	local original_tab = vim.api.nvim_get_current_tabpage()
	vim.cmd("tabnew")
	local test_tab, win = vim.api.nvim_get_current_tabpage(), vim.api.nvim_get_current_win()
	local first = section("src/first.lua", { "shared context", "first before" }, { "shared context", "first after" })
	local second = section("src/second.lua", { "shared context", "second before" }, { "shared context", "second after" })
	local view, replacement
	local ok, err = xpcall(function()
		view = Continuous.View.new({ winid = win, sections = { first, second }, context = 3 }):open()
		local buffer = view.bufnr
		assert(first.last < second.first, "file sections must occupy disjoint row ranges")
		for _, file in ipairs({ first, second }) do
			local row = file.body_first + file.map.from_new[2] - 1
			vim.api.nvim_win_set_cursor(win, { row, 3 })
			local selected, source_line, source_column = view:source_position()
			assert(
				selected == file and source_line == 2 and source_column == 3,
				"each file must resolve its own source coordinates"
			)
			assert(view:column_for("new").map.from_new[2] == row, "reverse lookup must follow the active file")
		end

		local first_row = first.body_first + first.map.from_new[2] - 1
		local second_row = second.body_first + second.map.from_new[2] - 1
		assert(view:selection_in_one_section(first_row, first_row), "a source-line note must be allowed")
		assert(not view:selection_in_one_section(first.first, first_row), "a file header is not a source anchor")
		assert(not view:selection_in_one_section(first_row, second_row), "a range must not span files")
		assert(not view:selection_in_one_section(second_row, first_row), "upward ranges must not span files")

		-- Both models number their first hunk as 1: navigation must retain file identity.
		vim.api.nvim_win_set_cursor(win, { first_row, 0 })
		view:jump_hunk("next")
		assert(view:active_section() == second, "next hunk must cross the file boundary")
		view:jump_hunk("prev")
		assert(view:active_section() == first, "previous hunk must cross back")
		view:jump_file("next")
		assert(view:active_section() == second, "file navigation must resolve the next section")
		assert(vim.api.nvim_get_current_buf() == buffer, "navigation must retain one scrolling buffer")

		-- Growing an earlier section must not move the cursor onto another source line,
		-- replace later file content, or recompute the unchanged file's diff.
		vim.api.nvim_win_set_cursor(win, { second_row, 3 })
		local events = {}
		vim.api.nvim_buf_attach(buffer, false, {
			on_lines = function(_, _, _, begin_row, end_row, new_end_row)
				events[#events + 1] = { begin_row, end_row, new_end_row }
			end,
		})
		local unchanged_map = second.map
		local updated = model(
			"src/first.lua",
			{ "shared context", "first before" },
			{ "shared context", "first after", "extra line" }
		)
		view:set_model(first, updated)
		wait("updated source rows should be rendered", function()
			return first.map.from_new[3] ~= nil
		end)
		assert(#events > 0, "updating a file must publish new buffer content")
		for _, event in ipairs(events) do
			assert(event[2] < second_row, "a section update must not replace unaffected later file content")
		end
		assert(second.map == unchanged_map, "an unchanged file must retain its rendered line map")
		local selected, line, column = view:source_position()
		assert(selected == second and line == 2 and column == 3, "section growth must preserve logical cursor position")

		-- Inline notes coexist across files even though the cursor has one active
		-- source model. Each extmark must use its own file's translated source row.
		local local_review = require("config.differ_local_review")
		local notes = {}
		for _, file in ipairs({ first, second }) do
			notes[#notes + 1] = {
				id = file.key,
				path = file.entry.path,
				body = "Review this source line",
				updated_at = "2026-09-07T00:00:00Z",
				source_range = { start = { side = "new", line = 2 }, ["end"] = { side = "new", line = 2 } },
				source_context = { line_text = file == first and "first after" or "second after" },
				anchor_status = "current",
			}
		end
		local note_session = {
			root = vim.fn.getcwd(),
			identity = local_review.store.current_identity(vim.fn.getcwd()),
			mode = "HEAD",
			document = { comparisons = { HEAD = { notes = notes } } },
		}
		local_review.render(note_session, view, false)
		local ns = vim.api.nvim_create_namespace("dotfiles.differ.local-review")
		local marks = vim.api.nvim_buf_get_extmarks(buffer, ns, 0, -1, {})
		assert(#marks == 2, "notes in both file sections must remain visible together")
		assert(marks[1][2] == first.body_first + first.map.from_new[2] - 2, "first note must anchor to the first file")
		assert(marks[2][2] == second.body_first + second.map.from_new[2] - 2, "second note must anchor to the second file")
		view:jump_section(first)
		local_review.render(note_session, view, false)
		assert(
			#vim.api.nvim_buf_get_extmarks(buffer, ns, 0, -1, {}) == 2,
			"changing the active source must not erase another file's note"
		)
		local threads = require("differ.pr.threads")
		local pr = { view = view, threads = {} }
		for _, file in ipairs({ first, second }) do
			pr.threads[#pr.threads + 1] = {
				thread_id = file.key,
				path = file.entry.path,
				side = "RIGHT",
				line = 2,
				comments = { { author = "reviewer", body = "Review this line", created_at = "2026-09-07T00:00:00Z" } },
			}
		end
		threads.apply(pr)
		assert(#pr.thread_anchors == 2, "GitHub threads from both files must remain addressable")
		assert(
			pr.thread_anchors[1].row == marks[1][2] + 1 and pr.thread_anchors[2].row == marks[2][2] + 1,
			"GitHub threads must use file-specific aggregate rows"
		)
		assert(
			threads.next_anchor(pr.thread_anchors, buffer, pr.thread_anchors[1].row, "next") == pr.thread_anchors[2].row,
			"thread navigation must cross file boundaries"
		)

		-- A status change may reorder a file without changing its source coordinates.
		vim.api.nvim_win_set_cursor(win, { second.body_first + second.map.from_new[2] - 1, 3 })
		local position = view:snapshot_logical_position()
		local retained_map = second.map
		second.entry.staged, second.key = true, "staged\0" .. second.entry.path
		view.sections = { second, first }
		view:render()
		view:restore_logical_position(position)
		local moved, moved_line, moved_column = view:source_position()
		assert(
			moved == second and moved_line == 2 and moved_column == 3,
			"status-driven reordering must retain the selected file and source position"
		)
		assert(second.map == retained_map, "structural refresh must retain unchanged file maps")
		view.sections = { second }
		view:render()
		local retained_text = vim.api.nvim_buf_get_lines(buffer, 0, -1, false)
		view:set_model(first, model(first.entry.path, { "old" }, { "stale removed source" }))
		wait("removed-section completion should settle", function()
			return not view.render_scheduled
		end)
		assert(
			vim.deep_equal(retained_text, vim.api.nvim_buf_get_lines(buffer, 0, -1, false)),
			"late results must not resurrect a removed file section"
		)

		-- A completion belonging to a closed view must never populate its successor.
		view:close()
		local fresh = section("fresh.lua", { "old" }, { "fresh source" })
		replacement = Continuous.View.new({ winid = win, sections = { fresh } }):open()
		view:set_model(first, model("src/first.lua", { "old" }, { "stale source" }))
		assert(vim.api.nvim_win_get_buf(win) == replacement.bufnr, "stale completion must not replace the live view")
		assert(
			replacement:active_section() == fresh and fresh.model.new_text == "fresh source\n",
			"stale completion must preserve successor data"
		)
		assert(vim.v.errmsg == "", "asynchronous rendering must not report errors: " .. vim.v.errmsg)
	end, debug.traceback)
	if replacement then
		replacement:close()
	end
	if view then
		view:close()
	end
	if vim.api.nvim_tabpage_is_valid(test_tab) then
		vim.api.nvim_set_current_tabpage(test_tab)
		vim.cmd("tabclose!")
	end
	vim.api.nvim_set_current_tabpage(original_tab)
	assert(ok, err)
	pending_open_ownership()
	print(
		"Continuous review: file-aware source maps, range boundaries, navigation, incremental updates, and closed-view ownership passed"
	)
end

return M
